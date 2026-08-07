# TechTrend — Main Concept

> A news app. The user describes what they want to follow **in their own words**.
> Every day they open one dashboard and see the things worth knowing — ranked,
> with no duplicates, and with a bottom.

This folder is the decomposed reference. [`../architecture.md`](../architecture.md) is the
single-file source of truth; every document here is a view onto one part of it.

---

## The concept in one page

Every news product answers three questions. TechTrend answers all three differently.

| Question | The usual answer | TechTrend's answer |
| --- | --- | --- |
| **What does the user want?** | Pick topics from our list | They write a sentence; we expand it into a keyword list they can see and edit |
| **What is worth showing?** | Whatever is loudest — clicks, recency, volume | Whatever is **new** — measured against 30 days of prior coverage on the subject |
| **Who does feedback affect?** | Everyone, via aggregate signals | **Only that user.** The story itself never changes |

Those three answers are the product. Everything else in this folder is the machinery
that makes them true at scale.

### Why "new, not loud" is the load-bearing idea

Interest is not a property an article has on its own. The sixth article this week about
the same event is boring even though it looks identical to the first. So interest is
measured **relative to what has already been published** — see [Judge](06-judge.md).

This single decision propagates everywhere:

- It requires a **corpus**, not a stream → [Collect](03-collect.md)
- It requires **grouping**, so 50 outlets on one event are one thing → [Group](05-group.md)
- It gives feedback **axes to generalise along** → [Feedback](09-feedback.md)
- It makes the dashboard safe to end → [Deliver](08-deliver.md)

### Why the economics work

Nothing expensive scales with the number of users.

- **Judge once per story, not per article.** Fifty articles on one event cost one AI call.
- **Share topics between users who describe the same thing.** Ten thousand people typing
  a version of "AI news" collapse to a handful of topic rows — one matching job, ten
  thousand readers.

Doubling the audience roughly doubles only the cheapest line. Detail in
[Cost model](13-cost.md).

---

## The shape of the system

**Three layers, information flows downward only.** This is the structural rule that keeps
the system predictable and unmanipulable — see [Three layers](02-three-layers.md).

```
SHARED    articles · stories · summaries · novelty · type · source
          computed once, identical for everyone, forever
                            │ reads
TOPIC     keyword lists · match scores
          shared between users whose lists are the same
                            │ reads
PERSONAL  weights · history · feedback
          one user; reads above, writes nothing outside
```

**Six stages, one pipeline.** Each stage is a document in this folder.

```
Collect ──▶ Read ──▶ Group ──▶ Judge ──▶ Match ──▶ Deliver ──▶ Feedback
  §3        §4        §5        §6        §7        §8          §9
  │         │         │         │         │         │            │
 feeds     JSON-LD   one       one AI    topics   one         personal
 sitemaps  +body     story     call per  indexed  ordered     weights
 ETags     embedding per       story     backward dashboard   only
                     event
└──────────── SHARED layer ────────────┘└─ TOPIC ─┘└──── PERSONAL ────┘
```

---

## Documents

### The premise

| # | Document | What it settles |
| --- | --- | --- |
| 1 | [The idea](01-the-idea.md) | The three differences that define the product |
| 2 | [The three layers](02-three-layers.md) | The structural rule everything else obeys |

### The pipeline

| # | Document | Turns | Into |
| --- | --- | --- | --- |
| 3 | [Collect](03-collect.md) | ~20,000 sites | a stream of new article URLs |
| 4 | [Read](04-read.md) | an HTML page | structured fields + an embedding |
| 5 | [Group](05-group.md) | many articles | one story per event |
| 6 | [Judge](06-judge.md) | one story | summary, type, **novelty**, hedge density |
| 7 | [Match](07-match.md) | a sentence + stories | topics, and stories scored against them |
| 8 | [Deliver](08-deliver.md) | matched stories | one ordered dashboard with an end |
| 9 | [Feedback](09-feedback.md) | user actions | personal weights, and nothing shared |

### The system

| # | Document | Covers |
| --- | --- | --- |
| 10 | [The user's journey](10-user-journey.md) | First minute, and every day after |
| 11 | [Data model](11-data-model.md) | Tables per layer; Postgres · Redis · S3 |
| 12 | [What runs where](12-runtime.md) | API + workers, no broker, no scheduler |
| 13 | [What it costs](13-cost.md) | What scales with what — the business case |

### The commitments

| # | Document | Covers |
| --- | --- | --- |
| 14 | [Rules that must not break](14-invariants.md) | 12 invariants: legal, quality, structural |
| 15 | [Build order](15-build-order.md) | Six steps, risk front-loaded on purpose |
| 16 | [Still open](16-open-questions.md) | Four decisions, four measurements |

---

## Reading paths

**New to the project** → [The idea](01-the-idea.md) → [Three layers](02-three-layers.md) →
[Judge](06-judge.md) → [Deliver](08-deliver.md). That is the product.

**Going to build it** → [Build order](15-build-order.md) first, then the stage you're on.
Do not skip step 3.

**Reviewing a design decision** → [Rules that must not break](14-invariants.md). If a
change violates one of the twelve, the change is wrong, not the rule.

**Deciding whether it's viable** → [Cost model](13-cost.md) →
[Still open](16-open-questions.md). The topic-deduplication measurement is the one that
can invalidate the design.

---

## The four things that would make this fail

Collected from across the document, because they are easy to miss when reading section
by section:

1. **Topics don't deduplicate.** If a million users produce 4M distinct topics instead of
   ~300k, matching cost stops being flat and the economics change.
   → [Still open](16-open-questions.md)
2. **Novelty doesn't predict interest.** The entire ranking premise rests on it and it is
   unvalidated. → [Judge](06-judge.md)
3. **Clustering merges wrong things.** Duplicates are the fastest way to lose a user;
   a wrong merge is worse than a missed one. → [Group](05-group.md)
4. **Matching is bad on hand-written keyword lists.** No amount of AI expansion rescues a
   matcher that fails on a careful manual list. → [Build order](15-build-order.md)
