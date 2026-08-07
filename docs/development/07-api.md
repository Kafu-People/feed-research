# 7 — API surface

← [AI layer](06-ai-layer.md) · [Dev README](README.md) · next → [Web app](08-web-app.md)

FastAPI. Thin: HTTP shape, auth, serialisation. **No ranking or matching logic lives here** —
that is `personal/rank.py` and `topic/match.py`, so both stay unit-testable without HTTP
and can't grow a second implementation.

---

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/auth/signup` · `/v1/auth/login` · `/v1/auth/refresh` | Tokens |
| `POST` | `/v1/topics/draft` | **Sentence → editable chips + live preview** (the distiller) |
| `POST` | `/v1/topics` | Save a draft → fingerprint → subscribe |
| `GET` | `/v1/topics` | The user's subscriptions |
| `PATCH` | `/v1/topics/{id}` | Edit chips (writes to the user's own topic / `personal_excludes`) |
| `DELETE` | `/v1/topics/{id}` | Unsubscribe |
| `GET` | `/v1/dashboard` | **The one screen.** Ranked, deduped, capped, finite |
| `GET` | `/v1/stories/{id}` | Expanded card + the source list behind "14 sources" |
| `POST` | `/v1/events` | Feedback batch (see below) |
| `GET` | `/v1/suggestions` · `POST` `/v1/suggestions/{id}` | Proposed topic changes; accept/dismiss |
| `POST` | `/v1/devices` | Push token registration |
| `GET` | `/healthz` · `/readyz` · `/metrics` | Ops |

---

## The two that matter

### `POST /v1/topics/draft`

The screen that makes onboarding work ([match](../architecture/07-match.md)): what we
understood, the rate, and three real headlines — in about ten seconds.

```python
class TopicDraftIn(BaseModel):
    sentence: str = Field(min_length=3, max_length=500)

class TopicDraftOut(BaseModel):
    title: str
    must: list[str]
    should: list[str]
    entities: list[str]
    exclude: list[str]
    ambiguity: str | None = None        # "Apple — the company or the fruit?"
    options: list[str] = []
    count_7d: int                       # → "47 stories in the last 7 days"
    per_day: float                      # → "about 6 a day"
    preview: list[CardOut]              # three real headlines, right now
```

```python
@router.post("/topics/draft", response_model=TopicDraftOut)
async def draft(body: TopicDraftIn, user=Depends(current_user), db=Depends(session)):
    d = await ai.distill(body.sentence)              # ~1s, effort=low
    stats, preview = await topic.dry_run(db, d)      # runs the matcher against the corpus
    return TopicDraftOut(**d.model_dump(), count_7d=stats.count_7d,
                         per_day=stats.per_day, preview=preview)
```

`dry_run` calls the **same** `evaluate()` the matcher uses ([worker stages](05-worker-stages.md)).
If the preview used a different code path, the preview would be a lie — and the entire
value of "shows what we understood" would evaporate.

This is the one API path allowed to call the distiller. The `import-linter` contract
permits `api → ai` only through `topic.distill`; judging is worker-only
([repo layout](01-repo-layout.md)).

### `GET /v1/dashboard`

```python
class CardOut(BaseModel):
    story_id: int
    headline: str
    summary: str | None                 # null when unjudged — degrade, don't drop
    source_name: str
    source_count: int                   # "14 sources"
    published_at: datetime
    image_url: str | None
    url: str                            # link OUT to the publisher
    topic_labels: list[TopicLabel]      # both labels when it matched two topics
    matched_by: list[str]               # enables "less about price targets"
    # NOTE: there is no `text` field. Invariant #1 is enforced by the schema.

class DashboardOut(BaseModel):
    cards: list[CardOut]
    generated_at: datetime
    done: bool = True                   # "That's today." — the bottom exists
    more: list[CardOut] = []            # below the line, for whoever wants it
```

```python
@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(user=Depends(current_user), db=Depends(session), cache=Depends(redis)):
    if hit := await cache.get_dashboard(user.id):
        return hit
    candidates = await load_candidates(db, user)     # matches ∩ subscriptions, minus seen
    weights    = await load_weights(db, user.id)
    cards      = rank(candidates, weights, now=utcnow())   # dedupe + caps + no padding
    cards      = insert_exploration_slot(cards, user)      # the anti-collapse slot
    out = DashboardOut(cards=cards[:MAX_CARDS], more=cards[MAX_CARDS:MAX_CARDS + 10])
    await cache.put_dashboard(user.id, out, ttl=300)
    await mark_shown(db, user.id, out.cards)               # positions recorded → bias correction
    return out
```

**`CardOut` has no body field.** [Invariant #1](../architecture/14-invariants.md) is
enforced by the absence of a place to put one — not by a reviewer noticing. The same
applies to `done`: there is no `?fill=true` parameter and no backfill branch, so
[invariant #10](../architecture/14-invariants.md) survives a future product manager.

`mark_shown` records **position**, which is what makes position-bias correction possible
in [feedback](../architecture/09-feedback.md). Without it, the ranker eventually learns
that position 1 is good and locks in whatever it already believed.

---

## Feedback

```python
class EventKind(str, Enum):
    SHOWN = "shown"; EXPANDED = "expanded"; DWELL = "dwell"
    TAPPED_THROUGH = "tapped_through"; SAVED = "saved"; SHARED = "shared"
    SCROLLED_PAST = "scrolled_past"; SKIPPED = "skipped"
    HIDDEN = "hidden"; BEST_OF_DAY = "best_of_day"
    # No CLICK member. Invariant #8 is enforced by the enum.

class EventIn(BaseModel):
    story_id: int | None
    kind: EventKind
    reason: str | None = None          # dismissal reason — rarest, most valuable
    dwell_ms: int | None = None
    position: int | None = None

@router.post("/events", status_code=202)
async def events(batch: list[EventIn], user=Depends(current_user), db=Depends(session)):
    """Batched and fire-and-forget. The app sends on screen-exit and on
    background; the client must never block a UI transition on this."""
    await record_events(db, user.id, batch)
    await enqueue("feedback", f"feedback:user:{user.id}:{today()}", {"user_id": user.id})
    return {"accepted": len(batch)}
```

Weight updates run in a worker, coalesced per user per day — a skip should not cost a
database round-trip on the interactive path.

**The clean-negative pipeline.** When a client reports the day complete, it sends a
`skipped` event for every card shown and not otherwise acted on. With a finite daily set
the user has seen everything, so those skips are real rejections — the property that lets
[feedback](../architecture/09-feedback.md) learn from hundreds of users instead of hundreds
of thousands. It only holds because `GET /dashboard` never pads.

Both surfaces compute that set with the **same shared function**
([shared client code](10-clients-shared.md)). Two client-side definitions of "shown" would
mean the weights were learned from a blend of two different signals.

---

## Auth

- Access token: JWT, 15 min. Refresh token: opaque, rotating, stored hashed, 90 days.
- Refresh reuse detection revokes the family — standard, and cheap to add now.
- Rate limits in Redis: `/topics/draft` 10/min/user (it makes an AI call), `/events`
  120/min/user, auth endpoints 20/min/IP.
- Every handler takes `user=Depends(current_user)`; there is no admin bypass in the user
  router.

---

## Caching

| Response | TTL | Invalidated by |
| --- | --- | --- |
| `GET /dashboard` | 5 min | New match for a subscribed topic; any feedback event |
| `GET /stories/{id}` | 1 h | Re-judge |
| `GET /topics` | — | Written through on edit |

The dashboard is the only thing that scales with users ([cost](../architecture/13-cost.md)),
so it is the only thing worth caching aggressively.

---

## Error shape

```json
{ "error": { "code": "topic_ambiguous", "message": "…", "detail": {...} } }
```

Codes are a closed enum shared with both clients via the generated OpenAPI client, so web
and mobile switch on a code rather than matching a message string
([shared client code](10-clients-shared.md)).

**The contract is additive-only**: new optional fields, never a removed or retyped one,
until the oldest supported mobile build is gone. Web updates in minutes; a native store
release takes days to weeks, so the slowest surface sets the rule and web inherits it.

---

## Admin router

Mounted separately, behind a different auth scheme, never on the public host:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/admin/sites` · `/admin/endpoints` | Site list management |
| `POST` | `/admin/sites/{id}/opt-out` | **Publisher removal — the 24h SLA path** |
| `GET` | `/admin/coverage` | Nightly GDELT diff, the gap queue |
| `GET` | `/admin/jobs` | Backlog by stage |
| `POST` | `/admin/rejudge` | Enqueue a re-judge backfill after a prompt change |

The opt-out endpoint is the mechanical half of
[invariant #3](../architecture/14-invariants.md); its SLA test lives in
[security & compliance](16-security-compliance.md).
