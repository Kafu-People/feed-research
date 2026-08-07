# 16 — Security & compliance

← [Deployment](15-deployment.md) · [Dev README](README.md) · next → [Milestones](17-milestones.md)

The legal rules in [invariants](../architecture/14-invariants.md) are the ones that can end
the product rather than degrade it. Each gets a code-level enforcement point, and the
strongest form is **the absence of a code path** — a rule you cannot break because the
mechanism doesn't exist.

---

## Rule #1 — never the article body

We serve headline + our own summary + thumbnail + link out.

| Enforcement | Where |
| --- | --- |
| `CardOut` has no `text` field | [API](07-api.md) |
| `articles.text_key` is an S3 key; the column cannot hold a body | [Database](03-database.md) |
| No endpoint returns `text_key` or proxies S3 | `api/schemas.py` |
| Regression test asserts the field's absence | [Testing](12-testing.md) |

```python
def test_card_schema_cannot_carry_a_body():
    assert "text" not in CardOut.model_fields
```

The body exists in S3 because judging and re-extraction need it. It has no route to a
client — not a filtered route, an absent one.

---

## Rule #2 — summaries genuinely rewritten

Two sentences in our own words, never a lightly edited lede. Enforced twice:

1. The judge prompt states it as a hard requirement.
2. `verify_rewritten()` rejects summaries with >25% 8-gram overlap against any source
   article ([AI layer](06-ai-layer.md)).

A failing summary is discarded and the story is marked unjudged — the card degrades to
headline + source. **We ship no summary rather than an infringing one.**

---

## Rule #3 — publisher opt-out within 24 hours

The only rule with a clock, so it gets the most machinery:

```python
# api/routers/admin.py
@admin.post("/sites/{site_id}/opt-out")
async def opt_out(site_id: int, db=Depends(session)):
    async with db.begin() as s:
        await s.execute(update(Site).where(Site.id == site_id)
                        .values(opt_out_at=utcnow()))
        await s.execute(delete(Job).where(Job.stage == "collect",
                                          Job.payload["site_id"].astext == str(site_id)))
        await enqueue("maintenance", f"purge:site:{site_id}",
                      {"site_id": site_id}, priority=1, session=s)
    telemetry.event("optout.received", site_id=site_id)
```

The purge job removes the site's articles and stories from serving. Three gates back it up:

```python
# collect worker — top of the handler
if ep.site.opt_out_at is not None:
    await disable_endpoint(deps.db, ep.id); return

# the endpoint claim query
WHERE ... AND s.opt_out_at IS NULL

# the ranker
candidates = [c for c in candidates if c.site.opt_out_at is None]
```

**Alerting fires at 12h — half the SLA** ([observability](13-observability.md)). A legal
commitment should page a human with time to act, not report a breach after the fact.

```python
async def test_opt_out_stops_collection_and_serving():
    await admin_opt_out(site_id)
    assert await claim_endpoints_for(site_id) == []
    assert not any(c.site_id == site_id for c in await dashboard(user))
```

---

## Rule #4 — never bypass a paywall

Enforced by the shape of the HTTP client, not by policy:

```python
class PoliteFetcher:
    """No cookie jar. No credential store. No auth-header parameter.
    No headless browser. No 'archive' fallback. The class cannot bypass
    a paywall because it has no mechanism to."""
    USER_AGENT = "TechTrendBot/1.0 (+https://techtrend.example/bot; bot@techtrend.example)"
```

This costs almost nothing because of the JSON-LD-first decision in
[read](../architecture/04-read.md): a paywalled article still yields headline, date, author
and image from the publisher's own markup, so it stays a first-class row. The rule is cheap
to keep precisely because the extraction design made it cheap.

---

## Rule #5 — launch outside the EU

Not an engineering fix. It is a deploy-region decision plus a signup-country gate, and it
appears on the [launch checklist](15-deployment.md). Revisit only with a licensing position
for the press publishers' right, not with a code change.

---

## Crawler citizenship

| Commitment | Mechanism |
| --- | --- |
| Honour `robots.txt` | Fetched, cached 24h, checked before every request. `respect_robots` is `true` in **every** environment |
| One or two connections per site | `per_host_concurrency: int = Field(le=2)` — an out-of-range value is a **startup failure** ([configuration](11-config.md)) |
| Identify honestly | UA carries a real, monitored contact address |
| Conditional requests | ETag / If-Modified-Since on every check; ~90% return 304 |
| Back off on failure | `failure_streak` ≥ 10 stops claiming the endpoint entirely |

Putting the concurrency ceiling in the type is the point: politeness constraints are exactly
the thing that gets "temporarily raised" under backlog pressure. It can't be, here.

---

## User data

| Data | Sensitivity | Handling |
| --- | --- | --- |
| Email | PII | Unique, indexed; never logged |
| Topic sentences | Reveals interests | Stored; not shared across users |
| `events`, `seen` | Behavioural | **Never leaves the personal layer** — invariant #11 |
| Push tokens | Device-linked | Rotatable, deleted on sign-out |

**The layer rule is a privacy property, not only an architectural one.** Because nothing
personal writes to anything shared, there is no aggregate behavioural profile to leak, sell,
or subpoena — the data doesn't exist in that form. `subscriber_count` on a topic is a count
of stated intent, never of behaviour ([three layers](../architecture/02-three-layers.md)).

### Deletion

```python
async def delete_account(user_id: int, db) -> None:
    """ON DELETE CASCADE removes subscriptions, weights, seen, events.
    Nothing in shared or topic references the user, so nothing is orphaned —
    which is the layer rule paying off as a compliance property."""
    await db.execute(delete(User).where(User.id == user_id))
    await decrement_subscriber_counts(db, user_id)
```

Deletion is a single `DELETE` because the schema has no back-references from shared tables.
Compare with a system where behaviour feeds a global model: there, deletion is a research
project.

---

## Application security

- **Auth**: JWT access (15 min) + rotating opaque refresh, stored hashed. Reuse detection
  revokes the token family.
- **Rate limits**: Redis. `/topics/draft` is 10/min/user because it makes an AI call —
  the only user-triggerable path with real marginal cost.
- **SQL**: SQLAlchemy parameter binding everywhere. No f-string SQL, enforced by review and
  by ruff's `S608`.
- **SSRF**: the fetcher resolves and rejects private IP ranges. Feed URLs are attacker-
  adjacent input — a publisher's feed can list any URL.
- **Untrusted HTML**: parsed with `selectolax`/`lxml`, never executed. No headless browser
  is in the dependency tree, which removes the whole category.
- **Secrets**: `SecretStr` for everything sensitive so tracebacks and `repr()` redact them;
  secrets manager in deployed environments ([configuration](11-config.md)).
- **Container**: non-root (`uid 10001`), read-only root filesystem, no shell in the runtime
  image beyond what the base provides.

---

## AI-specific

- **Prompt injection**: article text is untrusted input. The judge prompt frames it as data
  to summarise, the output is constrained by a schema, and — decisively — **the judge worker
  has no tools**. There is nothing for an injected instruction to actuate: the only possible
  output is a `JudgeResult`.
- **Refusals** are handled as content outcomes, not errors, and never drop a story
  ([AI layer](06-ai-layer.md)).
- **Never log summaries or article text** at INFO — logs are the easiest accidental route to
  a copy of the corpus somewhere it shouldn't be.
- **PII does not reach the model.** Judge sees article text; distill sees one sentence. No
  user identifier, email, or behavioural history is ever in a prompt.

That last point is worth stating plainly: the AI layer sits entirely in the shared and topic
layers. It never reads the personal layer, so there is no path by which one user's behaviour
could influence another user's summary.

---

## Incident response

| Incident | First action |
| --- | --- |
| Publisher complaint (load) | Drop the site's tier; check `per_host_concurrency` |
| Publisher complaint (content) | Opt out immediately, ask questions after |
| Hallucinated number shipped | Pull the story; check `judge.sentences_dropped`; re-run the verification suite |
| Credential leak | Rotate; audit `ai.judge` usage for anomalies |
| Data-subject deletion request | `delete_account()`; confirm within the statutory window |

The second row is the policy: a content complaint is resolved by removal first. The cost of
being wrong in that direction is one publisher's articles; the cost of being wrong in the
other direction is the product.
