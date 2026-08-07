# 15 — Deployment

← [Local development](14-local-dev.md) · [Dev README](README.md) · next → [Security & compliance](16-security-compliance.md)

**One image, two commands, both scale by adding copies**
([runtime](../architecture/12-runtime.md)). No Kubernetes at launch — a container host with
rolling deploys is enough until it demonstrably isn't.

---

## Image

```dockerfile
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 libxslt1.1 curl && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project    # deps layer, cached
COPY src/ ./src/
COPY migrations/ ./migrations/ alembic.ini ./
RUN uv sync --frozen --no-dev

RUN useradd -u 10001 -m app && chown -R app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"
HEALTHCHECK --interval=15s --timeout=3s CMD curl -fsS localhost:8000/healthz || exit 1
ENTRYPOINT ["techtrend"]
```

Same image for both processes. `CMD` differs:

```bash
techtrend api --host 0.0.0.0 --port 8000 --workers 4
techtrend worker --stage collect,read --concurrency 16
```

---

## Topology

| Service | Command | Scales with | Start at |
| --- | --- | --- | --- |
| `api` | `techtrend api` | **users** | 2 × small |
| `web` | `next start` | **users** | 2 × small |
| `worker-fetch` | `--stage collect,read` | articles/day | 2 × small |
| `worker-think` | `--stage group,judge,match` | stories/day | 2 × medium |
| `worker-maint` | `--stage maintenance` | fixed | 1 |

`web` is a separate image ([web app](08-web-app.md)) — Node, not Python — on the apex
domain, with the API at `api.`. Same-parent-domain keeps the refresh cookie first-party and
removes CORS preflights entirely. Deploy it independently of the API; it is a client, and
the API contract is additive-only so the two never need to move together.

**Splitting workers by stage is an operational convenience, not an architectural one.** They
are the same binary; the split exists so a judge backlog can be drained by adding
`worker-think` replicas without also multiplying crawler load on publishers.

`worker-maint` runs the nightly coverage diff, the job reaper, partition rotation and
retention. It is the only singleton — and it is safe as one because everything it does is
idempotent and re-runnable, so a missed night self-corrects.

### Sizing at launch

```
db      4 vCPU / 16 GB / 500 GB SSD    ← the single point of contention
cache   1 GB Redis
api     2 × (1 vCPU / 1 GB)
web     2 × (1 vCPU / 1 GB)
worker  4 × (2 vCPU / 4 GB)
```

~90 req/s of feed checks plus ~6 req/s of article downloads
([collect](../architecture/03-collect.md)) is genuinely one small server's worth of load.
Size the database first and everything else from measurement.

---

## Migrations

```bash
alembic upgrade head        # init container / release step, before new tasks start
```

**Expand → migrate → contract**, always, because rolling deploys mean old and new code run
simultaneously:

1. **Expand** — add the nullable column / new table. Deploy. Old code ignores it.
2. **Migrate** — backfill via a queue stage, not a long-running `UPDATE`.
3. **Contract** — drop the old column in a *later* release, once no running code reads it.

Rules that are not optional at this scale:

- `CREATE INDEX CONCURRENTLY` — a plain `CREATE INDEX` takes a write lock on `articles`
  and stops the pipeline.
- Never rebuild an HNSW index during a backfill. **Load first, index after**
  ([database](03-database.md)).
- Adding a NOT NULL column requires a default or a three-step expand/contract.
- Test every migration against a restored production-sized snapshot before shipping.

---

## Release

```
build image → push → run migrations → rolling replace api → rolling replace workers
```

- **API**: rolling, health-gated. `/readyz` fails until `bootstrap()` succeeds
  ([configuration](11-config.md)), so a misconfigured container never takes traffic and the
  rollout stalls instead of replacing good instances with broken ones.
- **Workers**: SIGTERM → stop claiming → finish in-flight → exit. `stopTimeout` ≥ the
  longest job (judge interactive: ~120s). A worker killed anyway is reclaimed by the reaper
  after 15 minutes — safe because every stage is idempotent
  ([worker stages](05-worker-stages.md)).
- **Rollback** is redeploying the previous image, which is only safe because of expand →
  migrate → contract: the previous code must still run against the current schema.

---

## Partition rotation

`matches` and `events` are range-partitioned ([database](03-database.md)):

```python
# maintenance stage, nightly
await create_partition("matches", next_month())
await create_partition("events",  next_month())
await drop_partition("matches", older_than=days(30))   # instant; recomputable
```

Creating **next** month's partition a month ahead is the important half. A missing partition
means inserts fail at midnight on the 1st — the classic version of this bug.

---

## Backups

Priority follows recoverability, not size ([database](03-database.md)):

| What | How | Restore target |
| --- | --- | --- |
| Postgres | Continuous WAL archiving + nightly base backup | PITR to any point in 7 days |
| S3 | Versioning + lifecycle | Object-level |
| Redis | **None** | Rebuilt from Postgres on start |

The irreplaceable data is `events`, `weights`, `seen`, `users`, `subscriptions` — the user's
own history, which cannot be regenerated at any price. Everything in the shared and topic
layers is recomputable, at worst at real AI cost.

**Restore drills quarterly.** An untested backup is a hypothesis.

---

## Scaling in order

| Symptom | First move |
| --- | --- |
| API latency up | Add `api` replicas; check the dashboard cache hit rate |
| Web TTFB up | Add `web` replicas — it is stateless; the dashboard SSR call is the only backend hop |
| Judge backlog | Add `worker-think`; verify batch is enabled |
| Read backlog | Add `worker-fetch` — but **not** past the per-host politeness cap |
| Postgres CPU high | PgBouncer transaction pooling; move heavy reads to a replica |
| Postgres saturated | Read replica for the API; keep the primary for queue + writes |
| Vector search slow | Tune HNSW `ef_search`; keep the 72h grouping window narrow |

"Add `worker-fetch`" has a hard ceiling that isn't about our capacity: per-host concurrency
is bounded at 2 by the config type ([configuration](11-config.md)). Scaling the crawler
means more hosts in flight, never more connections per publisher.

---

## Launch checklist

- [ ] Launch region **outside the EU** ([invariant #5](../architecture/14-invariants.md))
- [ ] `(app)/*` routes serve `noindex`; no public story archive ([web app](08-web-app.md))
- [ ] Refresh cookie is httpOnly + Secure + SameSite=Lax, on the apex domain
- [ ] CC-NEWS 30-day backfill loaded — without it novelty is meaningless and onboarding has
      nothing to preview ([collect](../architecture/03-collect.md))
- [ ] `robots.txt` honoured; UA carries a real, monitored contact address
- [ ] Opt-out endpoint tested end-to-end and **alerting at 12h**, half the SLA
- [ ] Backup restore drill passed
- [ ] The four dashboard numbers live ([observability](13-observability.md))
- [ ] `fingerprint_study.py` shipped, ready for the first 500 signups
      ([testing](12-testing.md))
