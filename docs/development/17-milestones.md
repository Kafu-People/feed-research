# 17 — Milestones

← [Security & compliance](16-security-compliance.md) · [Dev README](README.md)

[Build order](../architecture/15-build-order.md) turned into deliverables and exit criteria.
**The risk is front-loaded on purpose: steps 1–3 are where the design can be wrong.**

Each milestone lists what gets built, what must be true to move on, and — importantly —
what is deliberately *not* built yet.

---

## M0 — Skeleton (~3 days)

**Build:** repo, `pyproject.toml`, Docker, compose, Alembic, `platform/` (config, db, queue,
cache, blobs, telemetry), `cli.py` with both commands, CI with the `import-linter` contract.

**Exit:** `make dev` boots; a no-op job round-trips through the queue; `make check` is green;
a PR that makes `shared` import `personal` **fails CI**.

Getting the layer contract in on day one is the highest-leverage three lines in the project.
Retrofitting a boundary after code exists is a refactor; enforcing it from empty is free.

---

## M1 — Collect and look (~2 weeks)

**Build:** `sites`/`endpoints`/`articles`, `PoliteFetcher`, feed + sitemap parsing, adaptive
scheduling, `read` (JSON-LD → trafilatura → embedding), S3 storage, GDELT ingest + nightly
coverage diff, `seed-sites`, the frozen fixture corpus.

**No app, no accounts, no AI.** Then **look**.

**Exit — as numbers, not impressions:**

- [ ] **Articles/day from 100 sites.** Sizes everything downstream.
- [ ] **JSON-LD hit rate** on a 500-article sample. Decides how much extraction work exists.
- [ ] **Duplication rate** — how much of the volume is the same event.
- [ ] `coverage_ratio` ≥ 0.85 against GDELT.
- [ ] Feed breakage rate known and monitored.
- [ ] `tests/fixtures/corpus/` frozen and committed.

Two of the four [open measurements](../architecture/16-open-questions.md) are answered here
for free, by doing the step honestly.

**Not yet:** clustering, AI, topics, accounts.

> **Load the CC-NEWS 30-day backfill at the end of this milestone**, not later. Novelty
> needs 30 days of prior coverage to mean anything, and onboarding needs a corpus to preview
> against. Everything after M2 is misleading without it.

---

## M2 — Group and judge (~3 weeks)

**Build:** `stories`, candidate retrieval, 3-signal clustering, display-article selection,
`ai/` (client, schemas, prompts, batch), the judge worker, `verify_numbers`,
`verify_rewritten`, the hedge lexicon, importance, and a `print-top-stories` command.

**Exit:**

- [ ] **Clustering harness**: wrong merges ≤ 2 per 100 labelled clusters, with the
      precision-weighted objective ([testing](12-testing.md)).
- [ ] **Novelty harness**: AUC(novelty) > AUC(source authority). ***This is the experiment
      that validates §6.*** If it fails, stop and rethink the ranking premise — the rest of
      the architecture is unaffected.
- [ ] `verify_numbers` catches 100% of injected fake numbers in the test suite.
- [ ] `ai.judge.cache_read` > 0 — prompt caching demonstrably working.
- [ ] **You have read the day's top stories yourself, three mornings running, and it was
      worth reading.**

That last one is the actual acceptance test. Novelty scoring is judged by whether the top of
the list is worth a person's time; there is no offline metric that substitutes.

**Not yet:** topics, matching, accounts.

---

## M3 — Topics *(the gate)* (~2 weeks)

**Build:** `topics`/`topic_terms`/`matches`, fingerprinting, the reverse index, the two-phase
matcher (term + vector recall → gate → score), the ten hand-written keyword lists.

**Deliberately excluded: the distiller.** Hand-written lists isolate the matcher from the
generator, so a bad feed has exactly one possible cause.

**Exit:**

- [ ] **Matching harness** run on all ten hand-written topics.
- [ ] For each, you would personally subscribe to the output.
- [ ] Every false positive reviewed by a human.
- [ ] `must`/`exclude` verified as gates — the unit test where a perfect-scoring excluded
      story still returns 0.0.
- [ ] Candidate-set size bounded (hundreds, not millions).

> ***Do not move on until this is good.*** If matching is bad with a carefully hand-written
> list, **no amount of AI expansion rescues it.** This is the most important gate in the
> sequence.

---

## M4 — The distiller (~1.5 weeks)

**Build:** `ai/distill.py`, `TopicDraft`, `POST /v1/topics/draft`, `dry_run` (same
`evaluate()` the matcher uses), the ambiguity prompt, fingerprint deduplication.

**Exit:**

- [ ] **Expansion coverage**: for "AI chips", the draft contains H100, Blackwell, TSMC,
      ASML, entity list, BIS, and non-English spellings.
- [ ] Draft p95 latency < 2s.
- [ ] Preview shows three real headlines from the live corpus.
- [ ] Ambiguous sentences produce one question with buttons.
- [ ] A stranger's sentence produces chips they recognise as what they meant.

Expansion is where the value is — the difference between four results a week and fifteen a
day — and its quality is only measurable now that the matcher underneath is known-good.

---

## M5 — The web app *(first real users)* (~4 weeks)

**Build:** auth, `users`/`subscriptions`/`seen`/`events`, `GET /dashboard`, ranking with
dedup + caps + no padding, the client monorepo (`packages/api-client`, `packages/core`), and
the **Next.js web app** — six screens, feedback capture, the day-end `sendBeacon` flush.

Web leads because onboarding is a text box and a chip editor
([web app](08-web-app.md)): materially better with a keyboard, and shippable hourly while
the distiller prompt is still being tuned.

**Exit:**

- [ ] Sign-up → populated dashboard in under a minute.
- [ ] Dedup, caps, and the finite day verified by tests, not by looking.
- [ ] Feedback events land, including the clean-negative `skipped` flush — verified to
      survive a **closed tab** (`sendBeacon`), not just a clean navigation.
- [ ] `packages/core` tested once, in Node, covering both future surfaces.
- [ ] `(app)/*` is `noindex`; card link-out is a real `<a>` with `referrerPolicy="origin"`.
- [ ] First real users.
- [ ] **`fingerprint_study.py` run against the first 500 signups.**

## M5b — One store (~3 weeks, overlaps M6)

**Build:** the Expo app against the same `packages/core` — gestures, background flush,
push, store listing. **One** store, not both ([mobile app](09-mobile-app.md)).

**Exit:**

- [ ] Same six screens, same events, same shared rules — only affordances differ.
- [ ] `cleanNegatives` and the shown-threshold imported, not reimplemented.
- [ ] Backend contract confirmed additive-only; oldest supported build documented.
- [ ] Store review passed.

The second store follows only once the daily-digest habit is proven on the first.

> The fingerprint study is **the most important measurement in the project**
> ([cost](../architecture/13-cost.md)) and it costs one short script. If a million users
> would produce ~300k distinct topics, the design works comfortably; if 4M, matching cost
> stops being flat in users and the design needs revisiting. Run it the day there is data.

**Capture feedback from day one even though nothing consumes it yet** — M6 needs history
that only elapsed time produces.

---

## M6 — Learning (~3 weeks)

**Build:** `weights`, feedback → weight updates, editorial cold-start defaults,
position-bias correction, the exploration slot, `suggestions` (drift, terms, learned
excludes), digest + breaking notifications.

**Exit:**

- [ ] Weights move measurably within days of use.
- [ ] Position-bias correction verified against shuffled slots.
- [ ] The exploration slot is present and **not tunable to zero**.
- [ ] Every suggestion is proposed; `topics` is never written by a learning process.
- [ ] Digest fires at the user's hour; breaking capped at two/day; ignoring yields fewer.

The exploration slot will be the first thing someone tries to remove when engagement dips.
It is the only thing breaking the loop where the ranker trains on its own output
([feedback](../architecture/09-feedback.md)) — build it in from the start, and treat pressure
to remove it as the signal it's working.

---

## Sequence

```
M0 ─▶ M1 ─▶ M2 ─▶ M3 ═▶ M4 ─▶ M5 ─▶ M6
     └─ risk ──────┘  gate      web  │
                                     └─▶ M5b  one store
```

Each early step removes a specific way of being fooled later:

| Order | Confusion it prevents |
| --- | --- |
| M1 before M2 | Judging quality is unreadable without knowing volume and duplication |
| M2 before M3 | Match quality is unreadable if stories are duplicated or badly summarised |
| M3 before M4 | A bad feed could be the matcher or the distiller — hand-written lists eliminate one |
| M5 before M6 | Learning needs real feedback history; elapsed time cannot be shortcut |
| M5 before M5b | The shared `core` gets shaped by one working surface before a second consumes it — and store review is a bad place to discover the feedback queue is wrong |

---

## Where the three real bets get tested

| Bet | Tested at | If it fails |
| --- | --- | --- |
| **Distinct interests saturate** | M5 fingerprint study | Economics change; try harder normalisation and entity resolution before redesigning |
| **Novelty predicts interest** | M2 novelty harness | §6 and the ranking formula need rethinking; collect/group/layers/topics/delivery unaffected |
| **Clustering can be precise enough** | M2 clustering harness | Tune for precision; a missed merge is always the acceptable direction |

Everything else in this architecture is engineering with known answers. These three are the
bets, and the build order exists so each is answered before anything expensive is built on
top of it.
