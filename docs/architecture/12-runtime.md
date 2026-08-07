# 12 — What runs where

← [Data model](11-data-model.md) · [Main concept](README.md) · next → [What it costs](13-cost.md)

---

## The topology

```
       phone / web
            │
            ▼
      ┌──────────┐
      │   API    │   reads, ranks, returns
      └────┬─────┘
           │
   ┌───────▼────────────────────┐
   │  Postgres · Redis · S3     │
   └───────▲────────────────────┘
           │
      ┌────┴─────┐
      │ workers  │   collect · read · group · judge · match
      └──────────┘
```

> **Two things to run: the API and the workers.**
> Same code, different command. Both scale by adding copies.

---

## The two processes

| | API | Workers |
| --- | --- | --- |
| **Does** | reads, ranks, returns | collect · read · group · judge · match |
| **Layers touched** | reads all three, writes Personal | writes Shared and Topic |
| **Scales with** | users | articles/day and stories/day |
| **Latency profile** | interactive | batch, seconds to minutes |
| **Sections** | [Deliver](08-deliver.md), [Feedback](09-feedback.md) | [Collect](03-collect.md) → [Match](07-match.md) |

The split falls exactly on the layer boundary: **workers produce the shared and topic
layers; the API consumes them and owns the personal layer.** The deployment shape is the
architecture, not an incidental packaging choice.

The one interactive exception is topic creation ([Match](07-match.md)) — the distiller and
the live preview run on the API path, because *~2 seconds* is a product requirement
([Journey](10-user-journey.md)).

---

## Two things deliberately absent

### No message broker

> Jobs live in a **Postgres table**, claimed with `SELECT ... FOR UPDATE SKIP LOCKED`.

What this buys:

- One store to operate, back up and reason about
- Job state is **queryable with SQL** — "how many articles are stuck in extraction?" is a
  `SELECT`, not a broker dashboard
- Enqueueing a job is **transactional with the write that caused it** — no "row committed
  but message lost" class of bug
- Retries, dead-lettering and priority are columns, not broker features

`SKIP LOCKED` is what makes this scale to many workers without contention: each worker
claims rows nobody else holds, and a crashed worker's lock is released by the database.

### No scheduler process

> **Every schedule is a `next_check_at` column.**

[Collect](03-collect.md)'s ~20,000 endpoints across three tiers, plus adaptive back-off,
are all expressed as one indexed timestamp column. Workers poll for due rows.

What this buys:

- **No singleton to make highly available** — the classic cron/leader-election failure mode
  doesn't exist
- Adaptive intervals are an `UPDATE`, not a schedule mutation
- Adding a worker adds schedule throughput

The load this has to sustain is ~90 req/s of feed checks — an indexed
`ORDER BY next_check_at LIMIT n FOR UPDATE SKIP LOCKED` handles it on one small server.

---

## Stack

| | |
| --- | --- |
| **Backend** | **Python** — the extraction, embedding, NLP and AI-client ecosystem is where the work is |
| **App** | **React Native** — one codebase, though [Still open](16-open-questions.md) recommends launching **one platform first** |

---

## Operational consequences

| Property | Because |
| --- | --- |
| Scale the read path independently | API and workers are separate processes; add copies of either |
| Recover from a worker crash | Locks release, jobs are re-claimed; work is idempotent per article/story |
| Debug the pipeline | Every stage's queue and schedule is a SQL query |
| Backpressure | A slow stage grows its table; visible before it's an outage |
| Single point of contention | **Postgres.** It is the queue, the scheduler, the vector index and the store — size and monitor it as the whole system's floor |

The last row is the real trade-off. Consolidating on Postgres is right at this scale and
removes several classes of failure; the cost is that Postgres saturation degrades
everything at once. The mitigations already in the design: Redis absorbs the constant reads
([Data model](11-data-model.md)), S3 absorbs the bulk bytes, and `matches` is capped at 30
days because it is the one table that would otherwise grow without bound.
