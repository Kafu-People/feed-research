# 12 — Testing

← [Configuration](11-config.md) · [Dev README](README.md) · next → [Observability](13-observability.md)

Two separate things live here, and conflating them is a mistake:

- **Correctness tests** — does the code do what it says? Fast, deterministic, run in CI.
- **Quality harnesses** — is the *design* good? Slow, judgement-based, run on demand.

The harnesses are where the three real risks of this project get measured
([open questions](../architecture/16-open-questions.md)). They are not optional extras;
[build order](../architecture/15-build-order.md) gates on them.

---

## Correctness pyramid

```
tests/
├─ unit/          fast, no I/O — scoring, gating, fingerprints, verification
├─ integration/   testcontainers Postgres + Redis + MinIO — queue, workers, API
└─ quality/       the three harnesses (below) — not run in CI
```

```bash
make test        # unit + integration
make test-unit   # sub-second loop
make quality     # explicit, slow, costs money
```

### Unit — the invariant tests

These are the tests that matter most, because they encode rules that a well-meaning future
change would otherwise break:

```python
def test_gates_are_gates_not_weights():
    """A brilliant, novel, widely-covered gaming GPU story is still excluded."""
    topic = Topic(must=["GPU"], exclude=["gaming GPU review"], ...)
    story = perfect_story(text="The best gaming GPU review of 2027", novelty=1.0)
    score, _ = evaluate(topic, story)
    assert score == 0.0

def test_caps_drop_cards_and_never_rescore():
    cards = [card(topic=1, score=s) for s in (0.9, 0.8, 0.7, 0.6)]
    out = apply_caps(cards, per_topic=3, per_source=99)
    assert len(out) == 3
    assert [c.score for c in out] == [0.9, 0.8, 0.7]     # untouched

def test_short_day_stays_short():
    """There is no backfill path. Seven good things means seven cards."""
    out = rank(candidates(n=7), weights=neutral(), now=utcnow())
    assert len(out) == 7

def test_unverified_number_drops_the_sentence():
    r = JudgeResult(summary="Revenue fell 12%. Costs rose 40%.", ...)
    out = verify_numbers(r, [article(text="... revenue fell 12% ...")])
    assert out.summary == "Revenue fell 12%."

def test_event_kind_has_no_click():
    assert "click" not in {e.value for e in EventKind}   # invariant #8

def test_card_schema_cannot_carry_a_body():
    assert "text" not in CardOut.model_fields             # invariant #1
```

The last two look trivial and are not: they're regression guards on invariants that are
currently enforced by an *absence*. If someone adds a `text` field to `CardOut` in six
months, this test explains why they shouldn't.

### Integration — the ones that catch real bugs

```python
async def test_stage_is_idempotent(db, job):
    """The reaper reclaims crashed jobs. That is only safe because re-running
    a stage is a no-op. Every stage gets this test."""
    await read.run(job, deps)
    snap1 = await snapshot(db)
    await read.run(job, deps)
    assert await snapshot(db) == snap1

async def test_skip_locked_never_double_claims(db):
    await seed_jobs(db, n=100)
    claims = await asyncio.gather(*(claim(["read"], batch=10) for _ in range(10)))
    ids = [j.id for batch in claims for j in batch]
    assert len(ids) == len(set(ids)) == 100

async def test_layer_isolation(db, two_users):
    """One user's feedback must not move anything the other sees."""
    before = await dashboard(user_b)
    await hammer_feedback(user_a, hide_everything=True)
    assert await dashboard(user_b) == before

async def test_opt_out_stops_collection_within_sla(db):
    await admin_opt_out(site_id)
    assert await claim_endpoints_for(site_id) == []
```

`test_layer_isolation` is the executable form of
[invariant #11](../architecture/14-invariants.md), complementing the static
`import-linter` contract: the contract proves no import path exists, this proves no data
path does either.

---

## Fixtures: the frozen corpus

```
tests/fixtures/corpus/
├─ articles/          ~2,000 real articles, raw HTML, 3 subjects, 45 days
├─ clusters.jsonl     hand-labelled: which articles are the same event
├─ novelty.jsonl      200 stories, human "interesting / not" labels
└─ topics.jsonl       10 hand-written keyword lists + judged matches
```

Built once during [milestone 1](17-milestones.md) and **frozen**. Every harness scores
against the same corpus, so a threshold change produces a comparable number rather than an
anecdote. Kept in git LFS; the HTML is what makes re-extraction testable after a parser fix.

---

## Harness 1 — clustering

**Question:** does grouping merge the right things?
**Gate:** [build order](../architecture/15-build-order.md) step 2.

```bash
make quality-cluster           # sweeps cos/title/entity thresholds over clusters.jsonl
```

```
threshold sweep (cos × title × entity)
  cos=0.86 title=0.30 entity=0.50 →  wrong merges: 2   missed merges: 41   ← chosen
  cos=0.80 title=0.25 entity=0.40 →  wrong merges: 19  missed merges: 12
```

**Optimise for precision, not F1.** The scoring function weights a wrong merge ~10× a
missed one, because the failure modes are not symmetric
([group](../architecture/05-group.md)): a missed merge shows the same event twice and looks
like ordinary news; a wrong merge makes the app lie and silently disappears an event.

Also asserts the cost coupling: `stories/day` on the fixture set must stay within a band.
Under-merging shows up here as a cost regression before it shows up on the bill.

## Harness 2 — novelty

**Question:** does novelty predict interest **better than source authority alone**?
**Gate:** [build order](../architecture/15-build-order.md) step 2 — before anything is
built on the score.

```bash
make quality-novelty
```

```
n=200, one subject
  AUC(novelty)              0.71
  AUC(source authority)     0.58     ← the baseline that must be beaten
  AUC(novelty + authority)  0.74
```

> This is the experiment that validates §6 of the architecture and is **the
> second-most consequential measurement in the project**. Note the baseline: a novelty score
> that merely correlates with interest is not enough — it has to beat the cheap signal, or
> the whole stage is unjustified.

The same harness is the regression gate for prompt changes
([AI layer](06-ai-layer.md)): a new `judge.md` that moves AUC down does not ship.

## Harness 3 — matching

**Question:** with ten *hand-written* keyword lists, is the output good?
**Gate:** [build order](../architecture/15-build-order.md) step 3 — ***do not move on until
this is good.***

```bash
make quality-match
```

Reports precision / recall / stories-per-day per hand-written topic, plus every false
positive for eyeballing.

**Deliberately excludes the distiller.** Hand-written lists isolate the matcher from the
generator, so a bad feed has exactly one possible cause. Building the distiller first makes
every subsequent bad result ambiguous — which is why the build order puts this gate before
step 4.

Once the matcher is good, a fourth run compares distiller output against the hand-written
lists on the same corpus: **expansion coverage** — of the terms a human wrote, how many did
the model find, and what did it add?

---

## The measurement that isn't a test

**Do topics deduplicate?** One short script, run against the first 500 real signups
([milestone 5](17-milestones.md)):

```python
# scripts/fingerprint_study.py
rows = await db.fetch("SELECT sentence, fingerprint FROM signup_topics LIMIT 500")
print(f"{len(rows)} topics → {len({r.fingerprint for r in rows})} distinct")
```

It cannot run before real users exist, so it isn't part of any suite — but it is **the most
important measurement in the project** ([cost](../architecture/13-cost.md)). Ship the script
with milestone 5 so it runs the day there is data.

---

## AI in tests

- **Unit and integration tests never call Claude.** `AIClient` is injected via `Deps`; the
  fake returns fixture `JudgeResult`s. CI cost is zero and CI is deterministic.
- **Prompt regressions** are caught by the harnesses, on the frozen corpus, run explicitly.
- **Schema compatibility** has one live smoke test in CI-nightly: one real call asserting
  the response still parses into `JudgeResult`. It costs cents and catches an SDK or model
  change before it reaches the judge worker.

---

## CI

```yaml
lint:       ruff check && ruff format --check
types:      mypy src/
contracts:  lint-imports          # ← layer violations fail the build
unit:       pytest tests/unit -q
integration: pytest tests/integration -q     # testcontainers
```

`contracts` is the cheapest high-value job in the pipeline: it turns
[invariant #11](../architecture/14-invariants.md) from a review habit into a build error,
and it runs in under a second.
