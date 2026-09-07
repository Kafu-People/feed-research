# 14 — Local development

← [Observability](13-observability.md) · [Dev README](README.md) · next → [Deployment](15-deployment.md)

**Goal: `make dev` gives a working pipeline with real articles in under five minutes**, with
no AI key required. If the setup is slow or needs credentials, people stop running the whole
pipeline locally and start guessing.

---

## First run

```bash
git clone … && cd techtrend
cp .env.example .env
make dev            # compose up, migrate, seed 20 sites, start api + worker
make seed-corpus    # load the frozen test corpus — instant non-empty dashboard
open http://localhost:8000/docs
```

---

## compose

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment: [POSTGRES_PASSWORD=dev, POSTGRES_DB=techtrend]
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 2s
    command: >
      postgres -c max_connections=200
               -c shared_buffers=512MB
               -c log_min_duration_statement=500ms   # surface slow queries during dev

  cache:
    image: redis:7-alpine
    ports: ["6379:6379"]

  blobs:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment: [MINIO_ROOT_USER=dev, MINIO_ROOT_PASSWORD=devdevdev]
    ports: ["9000:9000", "9001:9001"]

  api:
    build: .
    command: techtrend api --reload
    env_file: .env
    ports: ["8000:8000"]
    volumes: ["./src:/app/src"]           # hot reload
    depends_on: {db: {condition: service_healthy}, cache: {…}, blobs: {…}}

  worker:
    build: .
    command: techtrend worker --stage collect,read,group,judge,match,maintenance
    env_file: .env
    volumes: ["./src:/app/src"]
    depends_on: {db: {condition: service_healthy}}
```

One worker runs every stage locally. In production they're the same image with different
`--stage` lists ([deployment](15-deployment.md)) — so the local topology is a subset of
prod, not a different thing.

---

## Makefile

```makefile
dev:              ## compose up + migrate + seed
	docker compose up -d db cache blobs
	docker compose run --rm api alembic upgrade head
	docker compose run --rm api techtrend seed-sites --count 20
	docker compose up -d api worker

seed-corpus:      ## load frozen fixture articles (no network, no AI)
	docker compose run --rm api techtrend seed-corpus tests/fixtures/corpus

migrate:          alembic upgrade head
revision:         alembic revision --autogenerate -m "$(m)"
psql:             docker compose exec db psql -U postgres techtrend
redis:            docker compose exec cache redis-cli

test:             pytest tests/unit tests/integration -q
test-unit:        pytest tests/unit -q
quality:          pytest tests/quality -q -s          ## slow; costs money
lint:             ruff check src tests && ruff format --check src tests
types:            mypy src
contracts:        lint-imports                        ## layer violations
check:            lint types contracts test

client:           ## regenerate the typed API client for BOTH clients
	curl -s localhost:8000/openapi.json > clients/packages/api-client/openapi.json
	cd clients/packages/api-client && pnpm openapi-typescript openapi.json -o src/schema.d.ts
	cd clients && pnpm -r build

web:              cd clients/apps/web && pnpm dev        ## localhost:3000
mobile:           cd clients/apps/mobile && npx expo start

backlog:          ## the operational one-liner
	docker compose exec db psql -U postgres techtrend -c \
	  "SELECT stage, state, count(*) FROM jobs GROUP BY 1,2 ORDER BY 1,2;"
```

---

## Working without an AI key

`make seed-corpus` loads pre-judged fixture stories, so the dashboard is populated and the
whole read path works with **zero AI calls**. For the write path:

```bash
TT_AI_FAKE=true make dev     # AIClient → FakeAIClient, deterministic JudgeResults
```

The fake lives in `techtrend/ai/fake.py` and returns fixture results keyed by story
content. Contributors touching collection, extraction, grouping, matching, ranking, the API
or either client never need a key — which is most of the codebase.

With a real key, set `TT_AI_BATCH_ENABLED=false` locally: the Batch API is right for
production economics and wrong for a five-second edit loop
([AI layer](06-ai-layer.md)).

---

## Seeding

| Command | Gives you |
| --- | --- |
| `seed-sites --count 20` | 20 real feed URLs across tiers A/B/C |
| `seed-corpus <path>` | ~2,000 fixture articles, pre-grouped and pre-judged |
| `seed-topics` | The hand-written keyword lists from the matching harness (17 of them) |
| `seed-user --email me@local` | A user subscribed to 3 topics, with plausible weights |

`seed-corpus` + `seed-topics` + `seed-user` reproduces a realistic dashboard in seconds,
which is what makes ranking and UI work possible without waiting for a crawl.

---

## Live crawling locally

```bash
docker compose exec worker techtrend crawl-once --site reuters.com
docker compose exec worker techtrend backlog
```

`crawl-once` runs collect → read → group → judge → match synchronously for one site and
prints each stage's output. It's the fastest way to see why one publisher extracts badly.

**Politeness holds locally.** `respect_robots` is `true` in every environment
([configuration](11-config.md)) and the fetcher's per-host cap is bounded by the type. A
convenient local override is exactly how a politeness rule stops being true in shipped code.

---

## Debugging

```sql
-- Why is nothing appearing?
SELECT stage, state, count(*) FROM jobs GROUP BY 1,2;
SELECT count(*) FROM endpoints WHERE next_check_at < now() - interval '5 minutes';

-- Why did this article get grouped there?
SELECT a.id, a.title, 1 - (a.embedding <=> :emb) AS cos
  FROM articles a
 WHERE a.published_at > now() - interval '72 hours'
 ORDER BY a.embedding <=> :emb LIMIT 10;

-- Why doesn't my topic match?
SELECT * FROM topic_terms WHERE topic_id = :id;
```

Every pipeline question is a SQL query, because the queue and the scheduler are tables
([job queue](04-job-queue.md)). That is the concrete daily payoff of not running a broker.

---

## Conventions

- **Migrations**: `make revision m="add facts to stories"`, then read the generated file.
  Alembic autogenerate misses enum changes and index options routinely.
- **`make check` before pushing** — same jobs as CI, same order.
- **Fixtures are frozen.** Adding to `tests/fixtures/corpus/` invalidates every harness
  baseline; if you must, re-run all three and record the new numbers
  ([testing](12-testing.md)).
