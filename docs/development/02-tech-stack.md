# 2 — Tech stack

← [Repo layout](01-repo-layout.md) · [Dev README](README.md) · next → [Database](03-database.md)

Every dependency, with the alternative it beat. Pin exact versions in `uv.lock`; the
majors below are the commitments.

---

## Backend

| Concern | Choice | Beat | Why |
| --- | --- | --- | --- |
| Language | **Python 3.12+** | Go, TypeScript | trafilatura, extruct, embeddings, the Anthropic SDK — the whole extraction/AI ecosystem is here. Go would win on the crawler and lose everywhere else |
| API framework | **FastAPI** | Litestar, Django | Pydantic-native (the API models *are* the validation), async-first, free OpenAPI for the RN client |
| Server | **uvicorn** (workers behind gunicorn in prod) | hypercorn | Standard, well-understood restart semantics |
| DB driver | **asyncpg** | psycopg3 | Fastest async Postgres driver; SQLAlchemy 2 supports it natively |
| ORM | **SQLAlchemy 2.0** async | raw asyncpg, SQLModel | Typed `select()` core API keeps hand-written SQL for the hot paths while giving migrations and relationships for the rest |
| Migrations | **Alembic** | hand-rolled SQL files | Autogenerate + downgrade + branch merging |
| Validation | **Pydantic v2** | dataclasses + manual | Same models validate HTTP, config, and AI structured output |
| Settings | **pydantic-settings** | os.environ | Typed, fail-at-boot config ([config](11-config.md)) |
| Queue | **Postgres** (`SKIP LOCKED`) | Celery+Redis, SQS, Kafka | One store to operate; enqueue is transactional with the write that caused it ([queue](04-job-queue.md)) |
| Cache | **Redis 7** | Postgres UNLOGGED tables | Dashboards and seen-sets are read constantly; keeping them off the primary protects the queue |
| Blobs | **S3** via boto3 | Postgres TOAST | Bodies never enter the DB ([invariant #1](../architecture/14-invariants.md)) |
| Vectors | **pgvector** (HNSW) | Qdrant, pinecone | One less system; recall at our scale (~1M articles/30d) is fine on HNSW |
| Packaging | **uv** | pip-tools, poetry | Fast resolves, real lockfile, single tool for venv + deps + run |

---

## Extraction and NLP

| Concern | Choice | Notes |
| --- | --- | --- |
| Feed parsing | `feedparser` | Handles the long tail of malformed RSS that a strict XML parser rejects |
| Sitemap parsing | `lxml` | News sitemaps are well-formed; no need for leniency |
| Structured metadata | `extruct` | JSON-LD / microdata / RDFa — the **first** extraction path ([read](../architecture/04-read.md)) |
| HTML parsing | `selectolax` | ~10× faster than BeautifulSoup; matters at ~6 articles/s |
| Body extraction | `trafilatura` | Fallback only, with a confidence score — low-confidence text is dropped rather than embedded |
| Entities | `spacy` (small models, per-language) | Needed by grouping and by `must`/`entities` gating |
| Language detect | `py3langid` | Fast, no model download; only used when `inLanguage` is absent |
| Hedge lexicon | hand-written, in-repo | [Judge](../architecture/06-judge.md)'s hedge score is a ratio over a word list — no model call, no dependency |

**`extruct` before `trafilatura` is a load-bearing ordering**, not a preference: it is what
makes paywalled articles first-class ([read](../architecture/04-read.md)) and therefore
what makes [invariant #4](../architecture/14-invariants.md) cheap.

---

## AI

| Concern | Choice | Notes |
| --- | --- | --- |
| Model | **`claude-opus-5`** via the `anthropic` Python SDK | Judge is the quality-critical, cost-dominant call |
| Output shape | **Structured outputs** (`messages.parse()` + Pydantic) | No free-text parsing anywhere in the codebase |
| Bulk path | **Message Batches API** | 50% cost on the non-urgent tail — see [AI layer](06-ai-layer.md) |
| Embeddings | pluggable provider behind `shared/read/embed.py` | Model choice is semi-permanent: changing it invalidates grouping, matching, and novelty windows |

Full contract, prompts, cost controls: [AI layer](06-ai-layer.md).

---

## Clients

Two surfaces — **web first, then one store** — sharing all non-visual logic.

| Concern | Choice | Beat | Why |
| --- | --- | --- | --- |
| Web | **Next.js** (App Router) + React DOM | Expo web (react-native-web) | Real `<a>` link-out, SSR, standard focus/scroll, ~150KB bundle. Link-out is the strongest feedback signal we have — it should be an anchor, not a synthetic press handler |
| Mobile | **React Native** + **Expo** | native × 2 | One codebase for both stores, and [ship one store first](../architecture/16-open-questions.md) |
| Shared logic | `packages/core` | duplicating per platform | The clean-negative rule must be byte-identical on both surfaces or the weights learn from a blend of two definitions |
| API types | generated from OpenAPI | hand-written | Types flow Postgres → Pydantic → OpenAPI → TS. None written by hand |
| Language | TypeScript, strict | — | |
| Data layer | **TanStack Query** | — | Cache, background refetch, optimistic feedback writes |
| Monorepo | **pnpm** workspaces + project references | nx, turborepo | Two apps and two packages doesn't justify a build orchestrator |

**The cost of this choice is two view layers.** It buys a web bundle with no React Native
compatibility shim, semantic HTML on a product that is fundamentally a reading list, and
platform-native affordances on each side (keyboard shortcuts vs. swipe). What keeps the two
from drifting into different products is that display *models*, copy, and the screen list
are shared — only the drawing differs.

Detail: [web app](08-web-app.md) · [mobile app](09-mobile-app.md) ·
[shared client code](10-clients-shared.md).

---

## Tooling

| Concern | Choice |
| --- | --- |
| Lint + format | **ruff** (both) |
| Types | **mypy** strict on `techtrend.*` |
| Layer contracts | **import-linter** ([repo layout](01-repo-layout.md)) |
| Tests | **pytest** + `pytest-asyncio` + `testcontainers` |
| HTTP mocking | `respx` |
| CI | GitHub Actions: lint → types → import-contracts → unit → integration |

---

## What we deliberately don't use

| Not used | Why |
| --- | --- |
| **Celery / RabbitMQ / SQS** | Jobs in Postgres are queryable, transactional with their cause, and one less thing to operate ([queue](04-job-queue.md)) |
| **Kubernetes** (at launch) | Two process types that scale by adding copies. A container host with a rolling deploy is enough until it isn't |
| **A separate vector DB** | pgvector handles the corpus size; a second store would need its own consistency story with `articles` |
| **Elasticsearch** | The reverse index is one table with two columns ([match](../architecture/07-match.md)). A search cluster to hold `topic_terms` is not justified |
| **GraphQL** | The client has ~8 endpoints and one shape that matters (the dashboard). REST + OpenAPI codegen is less machinery |
| **An ML training stack** | The personal layer is a few hundred interpretable weights per user ([feedback](../architecture/09-feedback.md)), updated with arithmetic |

The through-line: **at this scale, the number of systems to operate is a bigger risk than
the performance ceiling of any one of them.** Every row above trades a theoretical ceiling
for one less thing that can be down at 3am. The point where that stops being true —
Postgres saturation — is the known single point of contention
([runtime](../architecture/12-runtime.md)) and is what the observability doc watches first.
