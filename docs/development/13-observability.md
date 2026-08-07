# 13 — Observability

← [Testing](12-testing.md) · [Dev README](README.md) · next → [Local development](14-local-dev.md)

**structlog** (JSON) + **prometheus-client** + OpenTelemetry traces. The interesting part
isn't the stack — it's which numbers matter and which failures are silent.

---

## The four numbers

If a dashboard shows only four things, these:

| Metric | Meaning | Alert |
| --- | --- | --- |
| **`coverage_ratio`** | our articles ÷ GDELT's, per day | < 0.85 for 2 days |
| **`stories_per_day`** | drives the entire AI bill | ±40% week-over-week |
| **`ai_cost_per_story`** | cost ÷ stories judged | +25% week-over-week |
| **`pg_connections_used / max`** | the single point of contention | > 0.8 |

**`coverage_ratio` is the number the collection side is judged on**
([collect](../architecture/03-collect.md)) — not throughput, not fetch latency. A dead feed
and a quiet publisher look identical from the inside, so the only honest measure is the
outside view.

**`stories_per_day` and `ai_cost_per_story` move together and both point at clustering.**
Under-merging inflates story count, inflates the bill, and degrades novelty
([group](../architecture/05-group.md)). One bill, three symptoms — watch the pair, not just
the invoice.

**Postgres is the queue, the scheduler, the vector index and the store**
([runtime](../architecture/12-runtime.md)). Its saturation degrades everything at once, so
it leads the dashboard rather than sitting in an infrastructure sub-page.

---

## Metrics by stage

```python
# techtrend/platform/telemetry.py
JOBS       = Counter("tt_jobs_total", "", ["stage", "outcome"])
JOB_TIME   = Histogram("tt_job_seconds", "", ["stage"])
BACKLOG    = Gauge("tt_backlog", "pending jobs", ["stage"])
SCHED_LAG  = Gauge("tt_schedule_lag_seconds", "oldest overdue endpoint")
```

| Stage | Watch | Silent failure it catches |
| --- | --- | --- |
| collect | `coverage_ratio`, `schedule_lag`, 304 rate | A whole tier backing off after adaptive intervals drift |
| read | `jsonld_hit_rate`, `extraction_confidence` p50, empty-body rate | A site redesign quietly breaking extraction for one publisher |
| group | `stories_per_day`, `articles_per_story` p50/p99 | Under-merging — *before* it becomes an AI bill |
| judge | `ai.judge.*` tokens, `sentences_dropped`, `refusals` | Prompt or model drift |
| match | `matches_per_story`, `candidate_set_size` | Recall breadth creeping up and taking cost with it |
| api | latency p50/p95, `cards_per_dashboard` | A ranking bug that empties dashboards |

### The AI counters

From [the AI layer](06-ai-layer.md):

```
ai.judge.input / output / cache_read / cache_write
ai.judge.refusals
judge.sentences_dropped
```

> **`ai.judge.cache_read` flat at zero is an incident.** It means a silent cache
> invalidator has been introduced — a timestamp, a story id, a build hash interpolated into
> the system prompt. Nothing breaks; the bill roughly doubles. This is the highest-value
> cheap alert in the system.

> **`judge.sentences_dropped` rising** means the verification check
> ([invariant #7](../architecture/14-invariants.md)) is catching more hallucinated numbers
> than usual. The check is working — but the cause needs investigating, not celebrating.

---

## Logging

```python
log = structlog.get_logger()
log.info("judge.complete", story_id=s.id, articles=len(articles),
         novelty=s.novelty_score, story_type=s.story_type,
         effort=settings().ai_judge_effort, batch=not interactive,
         input_tokens=u.input_tokens, cache_read=u.cache_read_input_tokens)
```

Rules:

- **Never log article bodies or summaries** at INFO. Log ids and scores. Logs are the
  easiest accidental route to a copy of the corpus somewhere it shouldn't be
  ([invariant #1](../architecture/14-invariants.md)).
- **Never log settings wholesale** — an allowlist at boot only
  ([configuration](11-config.md)).
- Every job log carries `stage`, `key`, `attempts`, `job_id` so a failure and its retries
  join up.

---

## Tracing

One span per job, child spans for HTTP, DB, S3 and AI calls. The AI span carries model,
effort, batch flag, and usage — which makes "why did this story cost 8× the median" a trace
lookup rather than a guess.

---

## Alerts

**Page:**

| Alert | Threshold |
| --- | --- |
| API 5xx rate | > 1% for 5 min |
| Postgres connections | > 80% for 5 min |
| Any stage backlog | growing for 30 min |
| Judge stage fully stalled | zero completions for 15 min |

**Ticket:**

| Alert | Threshold |
| --- | --- |
| `coverage_ratio` | < 0.85 for 2 days |
| `ai.judge.cache_read` | zero over an hour with non-zero calls |
| `ai_cost_per_story` | +25% week-over-week |
| `stories_per_day` | ±40% week-over-week |
| Dead-lettered jobs | > 100 in a day |
| `jsonld_hit_rate` | drops > 10 points |
| **Publisher opt-out unprocessed** | **> 12h** — half the 24h SLA ([invariant #3](../architecture/14-invariants.md)) |

The opt-out alert fires at half the deadline deliberately: a legal commitment should page a
human with time to act, not report a breach after the fact.

---

## The daily digest

An internal email — the operational version of *"read it yourself for three mornings"*
([build order](../architecture/15-build-order.md)):

```
TechTrend — 2026-08-07
  articles       48,201    (+3% wk)
  stories         6,940    (+2% wk)   articles/story 6.9
  coverage        0.91                gaps: 12 sites (4 new, 8 broken feeds)
  judged          6,940    batch 91% / interactive 9%
  ai cost         $––      per story $––     cache read 87%
  sentences dropped  31    refusals 4
  topics          1,204 distinct / 9,880 subscriptions   ← the deduplication ratio
  dashboards      8,412    median 9 cards    empty 41

  Top 5 stories by importance:
    …
```

Two lines here are doing real work. **`topics distinct / subscriptions`** is the running
version of the most important measurement in the project
([cost](../architecture/13-cost.md)) — if that ratio drifts toward 1:1, the economics are
changing. And **`empty 41`** should never be zero: some users genuinely have quiet days, and
a suspiciously round zero would mean something is padding.

The "Top 5 by importance" block is there to be read by a person. If it stops being worth
reading, no metric on this page will tell you.
