# 16 — Still open

← [Build order](15-build-order.md) · [Main concept](README.md)

Four decisions to make and four things to measure. **The measurements are the ones that
can invalidate the design; the decisions only shape it.**

---

## To decide

| | Recommendation | Reasoning |
| --- | --- | --- |
| **Launch region** | **Outside the EU** | The press publishers' right is unsettled there and needs a licensing position, not an engineering fix — [Rules](14-invariants.md) #5 |
| **Money** | **Subscription, not ads** | **Ads reward exactly the behaviour rules 8–10 prevent** — raw clicks, padded days, endless scroll. The cost structure supports it: marginal cost per user is near-zero ([Cost](13-cost.md)) |
| **Domain at launch** | **Pick one — tech, or finance** | *"Everything"* is several products with different freshness rules and source lists ([Deliver](08-deliver.md) — decay rate is a property of the subject) |
| **Platform** | **One first** | Not both stores at once, despite React Native making both possible ([What runs where](12-runtime.md)) |

All four are the same decision in different clothes: **narrow the surface so the risky
parts get tested properly.** The design's real uncertainty is in novelty scoring and topic
deduplication, and neither is tested better by launching in more places.

The "money" row deserves emphasis — it is not primarily a business preference. An
ad-funded version of this product would come under continuous pressure to break rules 8, 9
and 10, and those rules are what make [Feedback](09-feedback.md) work at all.

---

## To measure

### 1. Do topics deduplicate?

**Fingerprint the first 500 real signups and count distinct values.**

```
1M users → 300k distinct topics   →  works comfortably
1M users →   4M distinct topics   →  matching cost rises sharply,
                                     the design needs revisiting
```

> ***This is the most important measurement in the project, and it costs one short
> script.***

| | |
| --- | --- |
| **Tests** | The second of the two decisions the economics rest on ([Cost](13-cost.md)) |
| **When** | [Build order](15-build-order.md) step 5, at first real users |
| **If it fails** | Matching stops being flat in users. Mitigations to explore first: more aggressive normalisation, entity resolution, clustering near-identical topics rather than requiring hash equality |

### 2. Does novelty predict interest?

**Take 200 stories in one subject, have a person mark each interesting or not, and check
whether the novelty score separates them better than source authority alone.**

| | |
| --- | --- |
| **Tests** | §6 — the central editorial claim of the product ([Judge](06-judge.md)) |
| **When** | [Build order](15-build-order.md) step 2, before anything is built on the score |
| **Note the baseline** | "Better than **source authority alone**" — a novelty score that merely correlates with interest isn't enough; it has to beat the cheap signal |
| **If it fails** | Ranking needs rethinking. The rest of the architecture — collect, group, layers, topics, delivery — is unaffected |

### 3. What fraction of pages carry JSON-LD?

**Sample 500.** Decides how much extraction work exists.

| | |
| --- | --- |
| **Tests** | The assumption in [Read](04-read.md) that most of the data is already structured |
| **When** | [Build order](15-build-order.md) step 1 |
| **Second-order effect** | Low coverage weakens the metadata-only path, which is what makes [Rules](14-invariants.md) #4 (never bypass a paywall) cheap |

### 4. How many articles a day does a 100-site list produce?

**Count it. Sizes everything downstream.**

| | |
| --- | --- |
| **Sizes** | download rate, embedding cost, stories/day, and therefore the AI bill ([Cost](13-cost.md)) |
| **When** | [Build order](15-build-order.md) step 1 |
| **Paired with** | The duplication rate from the same step — together they predict stories/day, the driver of the dominant cost line |

---

## What each answer changes

| Measurement | If it comes back badly | Scope of the damage |
| --- | --- | --- |
| Topics deduplicate | Matching cost scales with users | **Economics** — the business case in [Cost](13-cost.md) |
| Novelty predicts interest | The ranking premise is wrong | **Product** — §6 and the ranking formula |
| JSON-LD coverage | More extraction work; weaker paywall path | **Engineering effort** — bounded, not structural |
| Articles/day | Cost model is mis-sized | **Planning** — recalibrate, don't redesign |

**Only the first two can invalidate the design.** Both are cheap, both are answerable
early, and [Build order](15-build-order.md) is arranged so they are answered before
anything expensive is built on them.

---

## The honest summary of risk

Three things are assumed and not yet known:

1. **Distinct interests saturate** — that a million people describe a few hundred thousand
   things, not a few million.
2. **Novelty is what makes a story worth reading** — more than authority, more than volume.
3. **Clustering can be precise enough** — that a wrong merge is rare, since a wrong merge
   makes the app lie.

Everything else in this architecture is engineering with known answers. These three are
the bets.
