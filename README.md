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

**Prerequisites:** Docker, Python 3.12, Node 22 + pnpm 9, and `make`.

```bash
git clone https://github.com/arthasdev-bit/techtrend && cd techtrend
cp backend/.env.example backend/.env    # defaults work as-is, no keys needed
make install                            # backend venv + pnpm workspace
make dev                                # containers up, migrations, demo data
make api                                # backend → http://localhost:8000/docs
make web                                # web     → http://localhost:3000
```

That gives you a working pipeline with a non-empty dashboard in a few minutes.

**No API keys are required to run it.** `TT_AI_FAKE=true` in the example env swaps in a
deterministic stand-in for every model call, so the whole pipeline runs offline. Slack and
Gemini stay inert until you configure them — each checks for *both* halves of its config and
does nothing if either is missing.

Want real articles rather than the demo seed?

```bash
make worker                             # runs every stage; crawls the seeded sources
make backlog                            # jobs by stage and state — the health check
```

→ Full setup, including Slack and Gemini:
[docs/development/14-local-dev.md](docs/development/14-local-dev.md)

---

## Checks

```bash
make check       # lint + types + layer contracts + all tests
make test        # backend pytest + client vitest
make contracts   # layer violations only
```

| | |
| --- | --- |
| Backend tests | 298 (unit + integration against real Postgres, Redis and MinIO) |
| Shared client tests | 12 (vitest, Node — covers both surfaces at once) |
| Layer contracts | 3, enforced by `import-linter` in CI |
| Types | `mypy --strict`, zero errors across 77 source files |

`make test-unit` is the fast loop: no containers, no I/O, ~5 seconds.

---

## Status

**Running in production.** The full pipeline — collect, read, group, match, deliver — runs
continuously against ~90 real sources, and both Slack surfaces are live.

| | |
| --- | --- |
| Sources crawled | 87 sites, 99 feeds |
| Corpus | ~19,000 articles |
| Topics | 17 keyword topics, plus a user-managed research watchlist |
| Worker stages | 11 of 13 enabled (`judge` and `feedback` are off — see below) |

**Two things are deliberately switched off.** `judge` is the AI scoring pass; it has a
backlog of ~17,000 jobs and costs real money per story, so it is left out of the worker's
stage list. `feedback` belongs to personalisation, which was removed when the product moved
to a single shared board.

Full plan and history: [docs/development/17-milestones.md](docs/development/17-milestones.md).

---

## What it actually delivers

Two Slack channels, and they answer different questions.

**`#techtrend-ai` — the hourly report.** One message an hour carrying every story the hour
matched: headline as the link, publisher and topics beside it, and a plain-language summary
underneath. Plus a daily digest at 18:00 local.

**`#techtrend-briefs` — daily research.** A watchlist you manage from Slack with
`/techtrend`, researched with Gemini and Google Search grounding. The crawler reports what
publishers *published*; this reports what people *posted* — forum and discussion sources the
crawler cannot reach, because their robots.txt forbids it.

Each brief posts twice: the written explanation, and the same findings as tables. Every
topic runs at three rhythms — daily is what changed in 24 hours, weekly is the last 7 days,
monthly is the full picture.

Ask a question in any brief's thread and it answers, grounded in a live search, without
being mentioned.

→ [docs/development/18-research-briefs.md](docs/development/18-research-briefs.md)

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
