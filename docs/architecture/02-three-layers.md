# 2 — The three layers

← [The idea](01-the-idea.md) · [Main concept](README.md) · next → [Collect](03-collect.md)

Everything in the system belongs to one of three layers, and **information only flows
downward.** This is the rule that keeps the system predictable.

---

## The structure

```
┌────────────────────────────────────────────────────────────┐
│  SHARED                                                     │
│  articles · stories · summaries · novelty · type · source   │
│                                                             │
│  Computed once. Identical for every user, forever.          │
│  No user's behaviour can change anything here.              │
└──────────────────────────┬─────────────────────────────────┘
                           │  reads
┌──────────────────────────▼─────────────────────────────────┐
│  TOPIC                                                      │
│  keyword lists · match scores                               │
│                                                             │
│  Shared between users whose lists are the same.             │
└──────────────────────────┬─────────────────────────────────┘
                           │  reads
┌──────────────────────────▼─────────────────────────────────┐
│  PERSONAL                                                   │
│  weights · history · feedback                               │
│                                                             │
│  One user. Reads the layers above, writes nothing outside.  │
└─────────────────────────────────────────────────────────────┘
```

---

## What each layer owns

| Layer | Contains | Written by | Read by | Cardinality |
| --- | --- | --- | --- | --- |
| **Shared** | articles, stories, summaries, novelty, story type, source authority | [Collect](03-collect.md) · [Read](04-read.md) · [Group](05-group.md) · [Judge](06-judge.md) | everything | one row per real-world thing |
| **Topic** | keyword lists, embeddings, match scores | [Match](07-match.md) | Deliver, Personal | one row per *distinct* topic, N subscribers |
| **Personal** | weights, seen list, events | [Feedback](09-feedback.md) | Deliver | one row per user |

Table definitions per layer are in [Data model](11-data-model.md).

---

## Three things this buys

### Predictable

The same story looks the same to everyone. Only the **ordering** differs.

This is what makes support and debugging tractable: if two users disagree about what a
story says, one of them is wrong — there is no per-user version of the truth to reconcile.

### Unmanipulable

No amount of coordinated downvoting can move a shared value, **because no user writes to
the shared layer.** There is no mechanism to attack. This isn't a mitigation that can be
tuned or defeated; the write path does not exist.

### Stable

Each user's model is independent, so one going strange affects one person. There is no
shared ranker to poison, no feedback loop that lets a pathological cohort degrade the
product for everyone.

---

## The rule, stated precisely

> **A write may only target the layer the writer belongs to.**
> Personal code reads Topic and Shared. Topic code reads Shared.
> Nothing reads downward, and nothing writes upward.

Two invariants in [Rules that must not break](14-invariants.md) encode this:

- **#11** — Information flows down the three layers only. Nothing personal writes to
  anything shared.
- **#12** — Nothing changes a user's topic without asking them.

---

## Where the rule is under pressure

These are the places where a shortcut would violate the layering. Each has a sanctioned
alternative.

| Tempting shortcut | Why it violates | What to do instead |
| --- | --- | --- |
| "Trending" — boost stories many users opened | Aggregate personal behaviour writing into Shared | Boost on **source count** (how many outlets covered it), which is a shared fact |
| Cold start from similar users' weights | Aggregate personal data entering a Personal row | Start from **editorial defaults** ([Feedback](09-feedback.md)) |
| Auto-apply a learned exclusion to the topic | Personal signal writing into a *shared* Topic row | **Propose it**, never apply silently ([Match](07-match.md)) |
| Downrank a story everyone hides | Personal → Shared | Downrank it **for them**; it stays put for everyone else |
| Personalised summaries | Shared value becoming per-user | The summary is one text; ordering is what personalises |

The pattern: **anything that feels like collective intelligence is a layer violation.**
What survives is per-user learning made fast by clean negatives ([Feedback](09-feedback.md)),
and shared signals that are facts about publishing rather than facts about readers.

---

## The one legitimate aggregate

`subscriber_count` on a topic row — used for the discovery hint *"People following this
also follow: Semiconductor supply chain (2,341)"* ([Journey](10-user-journey.md)).

This is safe because it is a count of **stated intent**, not of behaviour, it lives in the
Topic layer rather than Shared, and it never enters any ranking computation.
