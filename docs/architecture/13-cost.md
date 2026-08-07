# 13 — What it costs

← [What runs where](12-runtime.md) · [Main concept](README.md) · next → [Rules that must not break](14-invariants.md)

---

## What scales with what

| | Scales with | Notes |
| --- | --- | --- |
| Collecting | number of sites | ~90 req/s. Small. |
| Downloading | articles/day | ~6 req/s |
| Embeddings | articles/day | cheap, batched |
| **Judging** | **stories/day** | **the main AI cost — one call per story** |
| Matching | stories/day | index lookups |
| Serving | users | the cheapest line |

---

## The business case, in one sentence

> **Nothing expensive scales with the number of users.**

Doubling the audience roughly doubles only **serving**. Collecting and judging barely move.

```
users ×2   →   serving ×2      (the cheapest line)
           →   collecting ×1
           →   judging   ×1
           →   matching  ×1
```

---

## The two decisions that produce it

### 1. Judge once per story, not per article

```
50 articles about one event  →  1 AI call
```

The expensive operation is bound to **events in the world**, which are finite and
roughly constant, rather than to **articles published**, which are not.

→ [Judge](06-judge.md) · depends entirely on [Group](05-group.md) being correct

### 2. Share topics between users who describe the same thing

```
10,000 users → a handful of distinct topics → one matching job
```

The matching operation is bound to **distinct interests**, which saturate, rather than to
**users**, which don't.

→ [Match](07-match.md)

**That's the whole business case.** Both are architectural decisions made early; neither
can be retrofitted cheaply.

---

## Where each cost line actually comes from

| Line | Driver | Controlled by |
| --- | --- | --- |
| Collecting | endpoints × tier frequency, minus ~90% ETag 304s | Tier assignment and adaptive back-off ([Collect](03-collect.md)) |
| Downloading | articles/day | Site list size |
| Embeddings | articles/day, batched | Model choice; a corpus-wide constant |
| **Judging** | **stories/day** | **Clustering precision** — the dominant control |
| Matching | stories/day × candidate-set size | Index recall breadth: ~few hundred keyword + ~200 vector ([Match](07-match.md)) |
| Serving | requests/user/day | Redis cache hit rate ([Data model](11-data-model.md)) |

---

## The two things that would break the model

### Clustering under-merges

Cost is `stories/day × price per call`. If clustering splits one event into five stories,
the AI bill is **5×** — and the novelty signal degrades at the same time, because reprints
start reading as new events ([Group](05-group.md)).

**Judging cost is the most sensitive metric to clustering quality**, and it is also the
earliest warning that clustering has drifted.

### Topics don't deduplicate

If a million users produce **4M** distinct topics rather than ~**300k**, matching stops
being a per-story index lookup against a small topic set and starts scaling with users —
which breaks the central claim of this section.

> This is the **most important measurement in the project**, and it costs one short
> script: fingerprint the first 500 real signups and count distinct values.
> → [Still open](16-open-questions.md)

---

## Consequences for pricing

[Still open](16-open-questions.md) recommends **subscription, not ads** — and the cost
structure supports it independently of the editorial argument:

- Marginal cost per user is near-zero, so subscription margin improves with scale
- Ads would reward exactly the behaviour [Rules](14-invariants.md) #8–10 prevent — raw
  clicks, padded days, endless scroll
- A cost structure that doesn't need volume is what makes a *finite day* affordable as a
  product decision rather than a sacrifice

**The economics and the editorial rules point the same direction.** That is not a
coincidence: both follow from ranking on what's new rather than what's loud
([The idea](01-the-idea.md)).
