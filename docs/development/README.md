# TechTrend — Development Architecture

How the system in [`../architecture.md`](../architecture.md) gets built: repo layout, module
boundaries, schema, worker contracts, API surface, AI layer, testing, deployment.

> [`../architecture/`](../architecture/) answers **what and why**.
> This folder answers **where the code goes and what it looks like**.

---

## The five decisions everything else follows from

**1. One deployable, two commands.**

```bash
techtrend api            # FastAPI — reads, ranks, returns
techtrend worker --stage collect,read,group,judge,match
```

Same image, same dependencies, same config. The stage list is a flag. There is no
"scheduler service", no "consumer service", no per-stage deployment.

**2. Postgres is the queue and the scheduler.**

`SELECT ... FOR UPDATE SKIP LOCKED` for jobs, `next_check_at` for schedules. No Celery, no
RabbitMQ, no cron container. Every piece of pipeline state is a SQL query
([job queue](04-job-queue.md)).

**3. Layer boundaries are package boundaries.**

`techtrend/shared/`, `techtrend/topic/`, `techtrend/personal/`. The import linter fails the
build if `shared` imports from `personal`. The rule from
[three layers](../architecture/02-three-layers.md) is mechanically enforced, not
documented and hoped for.

**4. Every worker stage is idempotent and re-runnable.**

Stages are pure-ish functions `(input, deps) -> output` with a natural idempotency key.
Re-processing an article must produce the same row, not a duplicate
([worker stages](05-worker-stages.md)).

**5. AI calls are one module with one contract.**

All Claude calls live in `techtrend/ai/`. Structured outputs, no free-text parsing. Batch
API for the tail, interactive for breaking news. Everything else in the codebase sees a
typed Pydantic model ([AI layer](06-ai-layer.md)).

---

## Stack

| Layer | Choice | Why |
| --- | --- | --- |
| Language | **Python 3.12+** | The extraction / embedding / NLP / LLM-client ecosystem is here |
| API | **FastAPI** + uvicorn | Async, Pydantic-native, OpenAPI for free |
| DB | **Postgres 16** + `pgvector` | Store, queue, scheduler, vector index — one system |
| ORM | **SQLAlchemy 2.0** (async) + **Alembic** | Typed core API; migrations that survive a team |
| Cache | **Redis 7** | Dashboards, seen sets, rate limiting |
| Blobs | **S3** (boto3) | Article text and raw HTML |
| Extraction | `trafilatura`, `selectolax`, `extruct` | JSON-LD first, body fallback |
| AI | **Claude** via `anthropic` SDK | `claude-haiku-4-5` on every stage (Opus banned), structured outputs, Batch API |
| Web | **Next.js** (App Router) + React DOM | First surface to real users; SSR, real anchors, keyboard |
| App | **React Native** (Expo) + TypeScript | Second surface; one store first, not both |
| Shared | `packages/core` + generated `api-client` | All non-visual client logic, written once |
| Packaging | **uv** + Docker + **pnpm** workspaces | Fast, lockfile-based, reproducible |

Detail and alternatives considered: [tech stack](02-tech-stack.md).

---

## The shape of the repo

```
techtrend/
├─ shared/        SHARED layer — collect, read, group, judge
├─ topic/         TOPIC layer  — distiller, matcher, index
├─ personal/      PERSONAL layer — ranking, feedback, weights
├─ ai/            all Claude calls, one contract
├─ platform/      db, queue, cache, blobs, config, telemetry
├─ api/           FastAPI routers
└─ cli.py         `techtrend api` / `techtrend worker`
```

Full tree, module responsibilities, and the enforced dependency rule:
[repo layout](01-repo-layout.md).

---

## Documents

### Foundation

| # | Document | Covers |
| --- | --- | --- |
| 1 | [Repo layout](01-repo-layout.md) | Package tree, module boundaries, import-linter contracts |
| 2 | [Tech stack](02-tech-stack.md) | Every dependency, with the alternative it beat |
| 3 | [Database](03-database.md) | Full DDL, indexes, partitioning, retention |
| 4 | [Job queue & scheduler](04-job-queue.md) | `SKIP LOCKED` claim loop, retries, `next_check_at` |

### The pipeline in code

| # | Document | Covers |
| --- | --- | --- |
| 5 | [Worker stages](05-worker-stages.md) | Per-stage contracts, signatures, idempotency keys |
| 6 | [AI layer](06-ai-layer.md) | Claude client, schemas, batching, caching, cost control |
| 7 | [API surface](07-api.md) | Endpoints, request/response models, auth, caching |

### Clients

Two surfaces, one set of rules. **Web ships first, then one store** — web has no review
queue, and onboarding is a text box plus a chip editor, which is materially better with a
keyboard.

| # | Document | Covers |
| --- | --- | --- |
| 8 | [Web app](08-web-app.md) | Next.js, SSR + auth cookies, keyboard shortcuts, `sendBeacon`, a11y |
| 9 | [Mobile app](09-mobile-app.md) | Expo RN, gestures, background flush, store releases |
| 10 | [Shared client code](10-clients-shared.md) | The monorepo: what's shared, what isn't, and why |

**Everything that isn't pixels is shared exactly once** — the feedback queue, the
clean-negative rule, card display rules, chips, formatting. Several invariants are only true
if both surfaces implement them identically, so those live in `packages/core` and are tested
once.

### Operating it

| # | Document | Covers |
| --- | --- | --- |
| 11 | [Configuration](11-config.md) | Settings model, env vars, secrets, per-environment |
| 12 | [Testing](12-testing.md) | Test pyramid, fixtures, and the three quality harnesses |
| 13 | [Observability](13-observability.md) | Metrics, the coverage number, logs, alerts |
| 14 | [Local development](14-local-dev.md) | compose, seed data, make targets |
| 15 | [Deployment](15-deployment.md) | Environments, migrations, scaling, backups |
| 16 | [Security & compliance](16-security-compliance.md) | Opt-out pipeline, PII, the paywall rule in code |

### Plan

| # | Document | Covers |
| --- | --- | --- |
| 17 | [Milestones](17-milestones.md) | Build order → concrete deliverables and exit criteria |

---

## Non-negotiables, as code

The twelve rules in [invariants](../architecture/14-invariants.md) are not comments. Each
one has an enforcement point:

| Rule | Enforced by | Where |
| --- | --- | --- |
| #1 never the article body | `ArticleOut` has no `text` field; body lives in S3 | [API](07-api.md) |
| #2 summaries rewritten | Judge prompt + verbatim-overlap check | [AI layer](06-ai-layer.md) |
| #3 opt-out in 24h | `sites.opt_out_at` gates the collect claim query | [Security](16-security-compliance.md) |
| #4 no paywall bypass | No cookie jar, no auth headers in the fetcher | [Worker stages](05-worker-stages.md) |
| #6 one story once | Unique index + dedup in the ranker | [Database](03-database.md) |
| #7 numbers verified | `verify_numbers()` runs before persist, always | [AI layer](06-ai-layer.md) |
| #8 no raw clicks | `EventKind` enum has no `click` member | [API](07-api.md) |
| #9 caps are hard | Applied post-sort as a filter, not a score term | [Worker stages](05-worker-stages.md) |
| #10 never pad | Ranker returns what qualifies; no backfill path exists on server **or** either client | [API](07-api.md) |
| #11 layers flow down | `import-linter` contract in CI | [Repo layout](01-repo-layout.md) |
| #12 no silent topic edits | Suggestions write to `suggestions`, never `topics` | [Database](03-database.md) |

**Rules #1, #4, #7, #8, #10 and #11 are enforced by the absence of a code path**, not by a
check that could be bypassed. That is the strongest form available: you cannot accidentally
serve an article body through an API model that has no field for it.

---

## Where to start

Building it → [milestones](17-milestones.md), then [local dev](14-local-dev.md).
Reviewing the design → [repo layout](01-repo-layout.md) → [database](03-database.md) →
[job queue](04-job-queue.md). Working on the AI → [AI layer](06-ai-layer.md).
