# 1 — Repo layout

[Dev README](README.md) · next → [Tech stack](02-tech-stack.md)

**The package tree is the layer diagram.** If a boundary in
[three layers](../architecture/02-three-layers.md) can't be expressed as an import rule, it
isn't really a boundary.

---

## Tree

```
techtrend/
├─ pyproject.toml
├─ uv.lock
├─ Makefile
├─ docker-compose.yml
├─ Dockerfile
├─ alembic.ini
├─ .importlinter                    ← layer contracts (CI-enforced)
│
├─ src/techtrend/
│  ├─ __init__.py
│  ├─ cli.py                        ← `techtrend api` / `techtrend worker`
│  │
│  ├─ platform/                     ← infrastructure; imported by everyone
│  │  ├─ config.py                  Settings (pydantic-settings)
│  │  ├─ db.py                      engine, session factory, Base
│  │  ├─ queue.py                   claim/complete/fail — SKIP LOCKED
│  │  ├─ cache.py                   Redis client + key builders
│  │  ├─ blobs.py                   S3 put/get, key scheme
│  │  ├─ http.py                    polite fetcher: robots, ETag, per-host limits
│  │  ├─ telemetry.py               structlog + prometheus + tracing
│  │  └─ types.py                   shared value objects (Url, Lang, Tier)
│  │
│  ├─ shared/                       ══ SHARED LAYER ══
│  │  ├─ models.py                  Site, Endpoint, Article, Story (SQLAlchemy)
│  │  ├─ collect/
│  │  │  ├─ feeds.py                RSS/Atom + sitemap parsing
│  │  │  ├─ schedule.py             adaptive next_check_at
│  │  │  ├─ gdelt.py                GDELT ingest + nightly coverage diff
│  │  │  └─ worker.py               stage entrypoint
│  │  ├─ read/
│  │  │  ├─ jsonld.py               NewsArticle extraction
│  │  │  ├─ body.py                 trafilatura fallback + confidence
│  │  │  ├─ embed.py                embedding client + batching
│  │  │  └─ worker.py
│  │  ├─ group/
│  │  │  ├─ candidates.py           72h candidate retrieval (pgvector)
│  │  │  ├─ cluster.py              3-signal agreement, display pick
│  │  │  └─ worker.py
│  │  └─ judge/
│  │     ├─ novelty.py              fact extraction + 30d comparison
│  │     ├─ hedge.py                lexicon ratio (no model call)
│  │     ├─ verify.py               numeric containment check
│  │     └─ worker.py
│  │
│  ├─ topic/                        ══ TOPIC LAYER ══
│  │  ├─ models.py                  Topic, TopicTerm, Match
│  │  ├─ distill.py                 sentence → keyword list
│  │  ├─ fingerprint.py             normalise → hash → dedupe
│  │  ├─ index.py                   reverse index maintenance
│  │  ├─ match.py                   recall (terms + vectors) → gate → score
│  │  ├─ upkeep.py                  drift, term suggestions, learned excludes
│  │  └─ worker.py
│  │
│  ├─ personal/                     ══ PERSONAL LAYER ══
│  │  ├─ models.py                  User, Subscription, Weight, Seen, Event
│  │  ├─ rank.py                    the scoring formula + caps + dedup
│  │  ├─ feedback.py                event → weight updates
│  │  ├─ explore.py                 the uncertainty slot
│  │  └─ digest.py                  notification assembly
│  │
│  ├─ ai/                           ══ ALL CLAUDE CALLS ══
│  │  ├─ client.py                  singleton, retries, telemetry
│  │  ├─ schemas.py                 Pydantic output models
│  │  ├─ prompts/                   *.md, cache-friendly, versioned
│  │  ├─ judge.py                   one story → JudgeResult
│  │  ├─ distill.py                 one sentence → TopicDraft
│  │  └─ batch.py                   Batch API submit/poll/collect
│  │
│  └─ api/
│     ├─ app.py                     FastAPI app factory
│     ├─ deps.py                    auth, session, current_user
│     ├─ schemas.py                 request/response models
│     └─ routers/
│        ├─ auth.py  topics.py  dashboard.py  feedback.py  admin.py
│
├─ migrations/                      Alembic
├─ tests/
│  ├─ unit/  integration/  fixtures/
│  └─ quality/                      the three harnesses (see testing doc)
└─ clients/                         pnpm workspace — see docs 8–10
   ├─ packages/  api-client · core
   └─ apps/      web (Next.js) · mobile (Expo)
```

---

## The dependency rule, mechanically

`.importlinter`:

```ini
[importlinter]
root_package = techtrend

[importlinter:contract:layers]
name = Information flows downward only
type = layers
layers =
    techtrend.api
    techtrend.personal
    techtrend.topic
    techtrend.shared
    techtrend.platform

[importlinter:contract:ai-is-a-leaf]
name = Only worker stages call the AI layer
type = forbidden
source_modules =
    techtrend.api
    techtrend.personal
forbidden_modules =
    techtrend.ai

[importlinter:contract:platform-is-independent]
name = Platform knows nothing about domain
type = forbidden
source_modules = techtrend.platform
forbidden_modules =
    techtrend.shared
    techtrend.topic
    techtrend.personal
```

`make lint` runs `lint-imports`. **A PR that makes `shared` import from `personal` fails
CI** — which is invariant #11 turned into a build error instead of a code-review habit.

The second contract is the interesting one: it means a request handler physically cannot
make an AI call. Judging happens in workers, once per story, or not at all — which is what
keeps the cost model in [cost](../architecture/13-cost.md) true.

---

## Module responsibilities

| Package | Owns | Must not |
| --- | --- | --- |
| `platform/` | DB sessions, queue, cache, S3, HTTP, config, telemetry | Know any domain concept |
| `shared/` | Articles, stories, and everything computed once | Read a `user_id` |
| `topic/` | Topics, the reverse index, matching | Write to `shared` tables |
| `personal/` | Weights, seen, events, ranking | Write to `topic` or `shared` |
| `ai/` | Prompts, schemas, retries, batching | Contain business rules |
| `api/` | HTTP shape, auth, serialisation | Contain ranking or matching logic |

`api/` being logic-free matters: it means the ranker is unit-testable without HTTP, and it
means an endpoint can't quietly grow a second implementation of the scoring formula.

---

## Naming conventions

- **Worker stage entrypoints** are always `worker.py` with `async def run(job, deps)`.
- **SQLAlchemy models** live in the layer's `models.py`, never in a shared `models` module —
  a single models file would let any layer import any table.
- **Pydantic API models** are suffixed `In` / `Out` (`TopicIn`, `CardOut`) and live in
  `api/schemas.py`. Never serialise a SQLAlchemy model directly; that's how article bodies
  leak ([invariant #1](../architecture/14-invariants.md)).
- **Prompts** are `.md` files under `ai/prompts/`, loaded at import, never f-strings —
  interpolating a timestamp into a prompt silently kills prompt caching
  ([AI layer](06-ai-layer.md)).

---

## Why `src/` layout

Tests import the installed package, not the working directory. This catches the class of
bug where a module works locally because of the CWD and fails in the container. With `uv`,
`uv sync` + `uv run pytest` gives an editable install and a real import path.
