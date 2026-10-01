# 5 — Worker stages

← [Job queue & scheduler](04-job-queue.md) · [Dev README](README.md) · next → [AI layer](06-ai-layer.md)

Every stage is `async def run(job: Job, deps: Deps) -> None`, keyed by an idempotency key,
and safe to re-run. That last property is what makes the crash-and-reclaim behaviour in
[the queue](04-job-queue.md) correct rather than merely convenient.

```python
@dataclass(frozen=True)
class Deps:
    db: async_sessionmaker
    http: PoliteFetcher
    blobs: BlobStore
    cache: Redis
    ai: AIClient
    embed: Embedder
```

| Stage | Job key | Enqueues | Idempotency |
| --- | --- | --- | --- |
| `collect` | `collect:endpoint:{id}` | `read:article:{url_hash}` | URL hash unique on `articles` |
| `read` | `read:article:{url_hash}` | `group:article:{id}` | Upsert on `url_hash` |
| `group` | `group:article:{id}` | `judge:story:{id}` | `story_id` set once; re-run is a no-op |
| `judge` | `judge:story:{id}` | `match:story:{id}` | `judged_at IS NULL` guard |
| `match` | `match:story:{id}` | `notify` / `hourly` | `PRIMARY KEY (topic_id, story_id)` upsert |

The five above are the article pipeline, and they run in order. The rest are delivery and
housekeeping: they are enqueued by a time bucket rather than by the stage before them, so
each one fires on its own schedule and none of them blocks the pipeline.

| Stage | Fires | What it does |
| --- | --- | --- |
| `hourly` | every hour, 4 min past | One report of the hour's matched stories to `#techtrend-ai` |
| `notify` | per story | The older per-story card. Unused while `slack_delivery_mode=hourly` |
| `summarize` | hourly | Summaries for cards that have none. Unused in hourly mode |
| `digest` | 18:00 local | The day's roll-up |
| `brief` | 09:00 local | The Gemini research watchlist — daily, plus weekly on Monday and monthly on the 1st |
| `discuss` | on demand | Answers a question asked in a brief's thread |
| `maintenance` | every 5 min | Reaps stale locks, purges done jobs |
| `judge` | **off** | AI scoring. Not in the worker's stage list: ~17,000 pending jobs, and it costs per story |
| `feedback` | **off** | Personalisation, removed when the product became one shared board |

The live stage list is in `backend/deploy/systemd/techtrend-worker.service`. A stage that is
in `HANDLERS` but not in that list simply never runs — which is how `judge` is disabled.

---

## Collect

```python
# techtrend/shared/collect/worker.py
async def run(job: Job, deps: Deps) -> None:
    ep = await load_endpoint(deps.db, job.payload["endpoint_id"])

    if ep.site.opt_out_at is not None:          # invariant #3, checked at the top
        await disable_endpoint(deps.db, ep.id)
        return

    resp = await deps.http.conditional_get(
        ep.url, etag=ep.etag, last_modified=ep.last_modified, site=ep.site,
    )
    if resp.status == 304:                       # ~90% of checks land here
        await bump_schedule(deps.db, ep, published=False)
        return

    links = parse_feed(resp.body) if ep.kind == "feed" else parse_sitemap(resp.body)
    fresh = [l for l in links if not await seen_url(deps.cache, l.url)]

    async with deps.db.begin() as s:
        for link in fresh:
            await enqueue("read", f"read:article:{sha256(canonical(link.url))}",
                          {"url": link.url, "site_id": ep.site_id,
                           "title_hint": link.title, "published_hint": link.published},
                          priority=10 if ep.site.tier == "A" else 100,
                          session=s)              # ← same transaction as the schedule bump
        await bump_schedule(s, ep, published=bool(fresh), etag=resp.etag)
```

**The politeness rules live in `PoliteFetcher`, not here**
([collect](../architecture/03-collect.md)):

```python
class PoliteFetcher:
    """robots.txt, per-host concurrency ≤ 2, honest UA with a contact address,
    conditional GETs. There is no cookie jar and no auth-header path — the
    class physically cannot bypass a paywall (invariant #4)."""
    USER_AGENT = "TechTrendBot/1.0 (+https://techtrend.example/bot; bot@techtrend.example)"
```

Making the paywall rule a property of the HTTP client rather than a policy in each caller
is the difference between "we don't do that" and "we can't do that".

### The nightly coverage audit

```python
# techtrend/shared/collect/gdelt.py — runs in the maintenance stage
async def coverage_diff(deps: Deps, day: date) -> list[CoverageGap]:
    """A dead feed and a quiet publisher look identical from the inside.
    GDELT is the outside view."""
    ours   = await counts_by_domain(deps.db, day)
    theirs = await gdelt_counts_by_domain(day)
    gaps = [
        CoverageGap(domain=d, ours=ours.get(d, 0), theirs=n,
                    kind="unknown_site" if d not in ours else "broken_feed")
        for d, n in theirs.items()
        if n >= 5 and ours.get(d, 0) < n * 0.5
    ]
    await enqueue_investigations(deps.db, gaps)
    telemetry.gauge("coverage.ratio", sum(ours.values()) / max(sum(theirs.values()), 1))
    return gaps
```

**`coverage.ratio` is the number this stage is judged on**
([collect](../architecture/03-collect.md)) — not throughput, not latency.

---

## Read

```python
# techtrend/shared/read/worker.py
async def run(job: Job, deps: Deps) -> None:
    resp = await deps.http.get(job.payload["url"], site_id=job.payload["site_id"])

    meta = extract_jsonld(resp.body)             # ← FIRST. Publisher's own markup.
    body = None
    if meta.wants_body:
        body = extract_body(resp.body)           # trafilatura fallback
        if body.confidence < 0.6:
            body = None                          # bad text poisons embeddings — drop it

    html_key = await deps.blobs.put_html(job.key, resp.body)
    text_key = await deps.blobs.put_text(job.key, body.text) if body else None

    article = await upsert_article(deps.db, Article(
        url=resp.final_url, url_hash=sha256(canonical(resp.final_url)),
        site_id=job.payload["site_id"],
        title=meta.headline or job.payload.get("title_hint"),
        published_at=meta.published_at or job.payload.get("published_hint") or resp.fetched_at,
        author=meta.author, image_url=meta.image, language=meta.language or detect(body),
        text_key=text_key, html_key=html_key,
        extraction={"source": "jsonld" if meta.complete else "mixed",
                    "confidence": body.confidence if body else None},
    ))

    article.embedding = await deps.embed.one(embedding_input(article, body))
    await enqueue("group", f"group:article:{article.id}", {"article_id": article.id})
```

**A paywalled article takes this path unchanged.** `meta` comes from JSON-LD, `body` is
`None`, and the article is a first-class row — which is why
[invariant #4](../architecture/14-invariants.md) costs almost no coverage
([read](../architecture/04-read.md)).

`embedding_input()` uses title + entities + lede when the body is absent, so grouping and
matching still work.

---

## Group

```python
# techtrend/shared/group/worker.py
async def run(job: Job, deps: Deps) -> None:
    art = await load_article(deps.db, job.payload["article_id"])
    if art.story_id is not None:
        return                                   # idempotent no-op

    candidates = await nearby_articles(deps.db, art, window=timedelta(hours=72), limit=50)
    best = pick_best(art, candidates)

    if best is not None:
        story_id = best.story_id
        await attach(deps.db, art, story_id)
        await recount_and_repick_display(deps.db, story_id)
    else:
        story_id = await create_story(deps.db, art)

    await enqueue("judge", f"judge:story:{story_id}", {"story_id": story_id},
                  priority=10 if art.site.tier == "A" else 100)
```

### Three signals must agree

```python
# techtrend/shared/group/cluster.py
COS_MIN, TITLE_MIN, ENTITY_MIN = 0.86, 0.30, 0.50

def same_event(a: Article, b: Article) -> bool:
    """Tuned for PRECISION. A missed merge shows the same event twice —
    annoying. A wrong merge makes the app lie and silently disappears an
    event — unrecoverable. The asymmetry is not close."""
    return (
        cosine(a.embedding, b.embedding) >= COS_MIN
        and jaccard(title_tokens(a), title_tokens(b)) >= TITLE_MIN
        and jaccard(a.entities, b.entities) >= ENTITY_MIN
    )
```

Thresholds live in one module and are swept by the clustering harness
([testing](12-testing.md)). Never tune them from a single anecdote.

### Display article

```python
def display_score(a: Article) -> float:
    return (0.5 * a.site.authority
            + 0.3 * (1.0 if is_wire_original(a) else 0.0)
            + 0.2 * (1.0 if a.image_url else 0.0))
```

---

## Judge

```python
# techtrend/shared/judge/worker.py
async def run(job: Job, deps: Deps) -> None:
    story = await load_story(deps.db, job.payload["story_id"])
    if story.judged_at is not None:
        return

    articles = await load_story_articles(deps.db, story.id)   # 1..50 articles → ONE call
    prior    = await prior_facts(deps.db, story.subject_key, days=30)

    result = await deps.ai.judge(story, articles, prior_facts=prior,
                                interactive=job.payload.get("priority", 100) <= 50)

    result = verify_numbers(result, articles)      # invariant #7 — not optional
    hedge  = hedge_ratio(articles)                 # lexicon, no model call

    story.summary       = result.summary
    story.story_type    = result.story_type
    story.novelty_score = apply_authority_guard(result.novelty, story, prior)
    story.hedge_score   = hedge
    story.facts         = [f.model_dump() for f in result.facts]
    story.importance    = compute_importance(story)
    story.judged_at     = utcnow()

    await enqueue("match", f"match:story:{story.id}", {"story_id": story.id})
```

The over-suppression guard from [judge](../architecture/06-judge.md):

```python
def apply_authority_guard(novelty: float, story: Story, prior: list[Fact]) -> float:
    """The same claim moving from an anonymous blog to Reuters IS new
    information. Without this, novelty systematically buries confirmations."""
    jump = story.max_authority - max((f.source_authority for f in prior), default=0.0)
    return min(1.0, novelty + 0.4 * jump) if jump >= 0.3 else novelty
```

Importance is precomputed here and stored on the story — identical for every user, per
[three layers](../architecture/02-three-layers.md):

```python
def compute_importance(s: Story) -> float:
    return (0.45 * s.novelty_score
            + 0.25 * s.max_authority
            + 0.15 * log_scale(s.source_count)
            - 0.10 * s.hedge_score
            - 0.05 * TYPE_PENALTY[s.story_type])
```

---

## Match

```python
# techtrend/topic/worker.py
async def run(job: Job, deps: Deps) -> None:
    story = await load_story(deps.db, job.payload["story_id"])

    # 1 + 2: RECALL — cheap, approximate, allowed to over-return
    by_term   = await topics_containing_terms(deps.db, tokens(story))       # few hundred
    by_vector = await topics_near(deps.db, story.embedding, limit=200)      # paraphrases

    # 3: PRECISION — exact evaluation on a bounded candidate set
    rows = []
    for topic in await load_topics(deps.db, by_term | by_vector):
        score, matched_by = evaluate(topic, story)   # must/exclude are GATES here
        if score >= topic.floor:
            rows.append(Match(topic.id, story.id, score, matched_by))

    await upsert_matches(deps.db, rows)
```

```python
# techtrend/topic/match.py
def evaluate(topic: Topic, story: Story) -> tuple[float, list[str]]:
    """must and exclude are hard gates, not weights. A user who says
    'not gaming GPUs' means it, and no score overrides that."""
    text = searchable(story)
    if any(term in text for term in topic.exclude):
        return 0.0, []
    hits = [t for t in topic.must if t in text]
    if not hits:
        return 0.0, []
    if topic.entities and not (set(topic.entities) & set(story.entities)):
        return 0.0, []

    shoulds = [t for t in topic.should if t in text]
    score = (0.5 * cosine(topic.embedding, story.embedding)
             + 0.3 * min(1.0, len(hits) / 2)
             + 0.2 * min(1.0, len(shoulds) / 3))
    return score, hits + shoulds
```

**Gates are early returns, not penalty terms.** A penalty a high enough score can defeat is
not a gate — the same principle as the diversity caps below.

---

## Ranking (read path, not a worker)

Lives in `personal/rank.py` and runs in the API, but the invariants belong here:

```python
def rank(cards: list[Candidate], w: Weights, now: datetime) -> list[Card]:
    for c in cards:
        c.score = (c.importance
                   * c.match_score
                   * freshness(c, now)              # decay rate is per-subject
                   * personal_multiplier(c, w))

    cards.sort(key=lambda c: c.score, reverse=True)
    cards = dedupe_by_story(cards)                  # invariant #6 — best score, both labels
    cards = apply_caps(cards, per_topic=3, per_source=3)   # invariant #9 — a FILTER, post-sort
    return cards                                    # invariant #10 — no backfill path exists
```

`apply_caps` runs **after** sorting and drops cards; it never adjusts a score. And there is
no `if len(cards) < N: fetch_more()` — a quiet day is allowed to be quiet, which is what
keeps skips clean for [feedback](../architecture/09-feedback.md).

---

## Adding a stage

1. Create `techtrend/<layer>/<stage>/worker.py` with `async def run(job, deps)`.
2. Register it in `HANDLERS` in `cli.py`.
3. Add the stage name to the deploy's `--stage` list.
4. Write the idempotency test first: **run the handler twice on the same job; assert the
   database is byte-identical.** That test is what lets the reaper exist.
