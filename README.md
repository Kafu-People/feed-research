# TechTrend

A news app. You describe what you want to follow **in your own words**. Every day you open
one dashboard and see the things worth knowing — ranked, with no duplicates, and with a
bottom.

Three things make it different: you write a **sentence**, not a topic choice; ranking is by
**what's new**, not what's loud; and **feedback is private** — it changes your ordering and
nobody else's.

---

## Layout

```
techtrend/
├─ backend/      Python 3.12 · FastAPI · Postgres · the pipeline
├─ clients/      pnpm workspace: shared core + web (Next.js) + mobile (Expo)
├─ docs/         architecture (what & why) and development (how)
├─ Makefile      every command you need
└─ docker-compose.yml   Postgres · Redis · MinIO
```

Two services, one level. `make help` lists everything.

---

## Quick start

```bash
make install     # backend venv + pnpm workspace
make dev         # containers up, migrations applied, demo data seeded
make api         # backend  → http://localhost:8000  (docs at /docs)
make web         # web      → http://localhost:3000
```

Sign in with **`demo@example.com` / `hunter2hunter2`**.

No Anthropic API key is needed: `TT_AI_FAKE=true` swaps in a deterministic stand-in, so
everything except the judging quality itself works offline.

---

## Checks

```bash
make check       # lint + types + layer contracts + all tests
make test        # backend pytest + client vitest
make contracts   # layer violations only
```

| | |
| --- | --- |
| Backend tests | 32 (unit + integration against real Postgres) |
| Shared client tests | 12 (vitest, Node — covers both surfaces at once) |
| Layer contracts | 3, enforced by `import-linter` in CI |

---

## Status

**M0 complete and verified** — skeleton, platform, queue, schema, API, both clients.

Worker stages (`collect`, `read`, `group`, `judge`, `match`) are placeholders. They land in
M1–M3, and **M3 is a gate**: matching must be good on hand-written keyword lists before the
distiller is built, or a bad feed has two possible causes instead of one.

Full plan: [docs/development/17-milestones.md](docs/development/17-milestones.md).

---

## The rules that don't bend

Twelve invariants in [docs/architecture/14-invariants.md](docs/architecture/14-invariants.md).
Six of them are enforced by **the absence of a code path**, which is stronger than a check
that could be bypassed:

| Rule | How it's impossible to break |
| --- | --- |
| Never the article body | `CardOut` has no text field; bodies live in S3 |
| Never bypass a paywall | The fetcher has no cookie jar and no auth-header parameter |
| Never rank on raw clicks | `EventKind` has no `click` member |
| Never pad a short day | There is no minimum-cards setting and no backfill branch |
| Information flows down only | `import-linter` fails the build |
| One or two connections per site | `per_host_concurrency` is `Field(ge=1, le=2)` — over-eager config is a *startup failure* |

---

## Docs

Start at [docs/README.md](docs/README.md).

- **[docs/architecture.md](docs/architecture.md)** — the single-file source of truth
- **[docs/architecture/](docs/architecture/)** — the same, decomposed: 16 concepts
- **[docs/development/](docs/development/)** — how it's built: 17 documents
