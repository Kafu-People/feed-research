# 9 — Feedback

← [Deliver](08-deliver.md) · [Main concept](README.md) · next → [The user's journey](10-user-journey.md)

**Stage 7 of the pipeline.** Layer: **Personal** — and it never leaves it.

| | |
| --- | --- |
| **In** | user actions on cards |
| **Out** | that user's weights, and nothing else |
| **Tables** | `weights`, `seen`, `events` ([Data model](11-data-model.md)) |

> **Every action writes to that user's row only.**
> Never to the story. Never to anyone else's dashboard.

---

## What we collect, strongest first

| Signal | Strength |
| --- | --- |
| Tapped through to the publisher | **strongest** — they left the app for it |
| Saved or shared | strong |
| Read the expanded card fully | good — dwell relative to summary length |
| Expanded it at all | moderate |
| Scrolled past fast | negative |
| Skipped entirely | negative, and **clean** |
| Dismissed with a reason | **most valuable, rarest** |

Note what is *absent*: the raw click. [Rules](14-invariants.md) #8 — rank on tap-through
and dwell, **never raw clicks** — otherwise the ranking learns that outrage works. A click
measures the headline; a tap-through and a dwell measure the article.

---

## Why "skipped" is clean

In an endless feed you can't tell **"didn't see it"** from **"rejected it."**

With a **finite daily set**, the user has seen everything. Every skip is a real negative.

```
endless feed   →  skip = ambiguous  →  needs 100,000s of users to average out
finite day     →  skip = rejection  →  needs 100s
```

> That means learning from hundreds of users what would normally need hundreds of
> thousands.

**This is the mechanism that makes private personalisation viable at all.** Without
collaborative filtering ([The idea](01-the-idea.md)), each user's model must be learned
from their own data — and clean negatives are what make that data dense enough.

It depends entirely on [Deliver](08-deliver.md) never padding. Filler in the set means
skips are no longer rejections, and the sample rate advantage disappears.

---

## Natural moments, not a rating chore

### End of day, one tap

After the last card: **"Best one today?"**

It arrives at the natural stopping point ([Deliver](08-deliver.md) — the bottom exists),
and **one tap ranks the whole set.** A single choice among ~8 known-seen items is a
complete ordering signal, not one data point.

### Dismiss with a reason

Swiping shows a brief toast: `Hidden · Why?`

Most ignore it. The ones who tap give the most valuable data in the system —

> because **a thumbs-down means at least five different things**, and conflating them
> teaches the wrong lesson.

Wrong topic · already knew it · don't trust the source · it's speculation · not interested
in this kind of story. Each implies a different weight to move. Undifferentiated negative
feedback moves the wrong one.

### Feedback on the keyword

**Unique to this design:** a card shows which keyword matched it, so the user can act on
the **keyword** rather than the article.

> *"Less about price targets."*

That edits the topic directly, and **the user sees exactly what changed.** It converts one
dismissal into a durable rule, and it is the highest-leverage feedback in the product
because it operates on the query rather than on a result.

---

## How the signals become learning

**Feedback alone teaches nothing generalisable** — one thumbs-down on one article is one
data point.

What makes it generalise is being able to **describe** what that article was:

```
analysis rather than reporting  ·  low novelty  ·  hedge-heavy
from this source  ·  matched by this keyword
```

> **Novelty, story type and hedge density are the axes feedback gets learned along.**
> Without them you're memorising individual articles.
> With them, **one dismissal generalises to a thousand future ones.**

All three axes are produced by [Judge](06-judge.md). This is the strongest coupling in the
architecture: **the value of the personal layer is bounded by the quality of the shared
descriptors.** Bad story-type classification doesn't just mislabel a card — it makes
learning impossible.

---

## What the personal layer holds

**Small** — a few hundred numbers per user, fitting in one row:

- a weight per **story type**
- a weight per **source**
- a weight per **keyword** in their own topics
- their **seen** list

Deliberately not a per-user neural model. Interpretable weights over shared axes are what
let the product *show* the user why something ranked where it did, and what let a
correction be applied directly rather than trained in.

---

## Two traps

### Position bias

Cards shown first get engaged with **regardless of quality.** Train naively and the model
learns *"position 1 is good"* and **locks in whatever it already believed.**

> Correct for it, or shuffle a slot occasionally.

### Collapse

A ranker trained **only on what it already showed** narrows fast.

> Reserve a slot or two a day for **genuine uncertainty** — things the model can't predict
> a response to. That's how it keeps learning instead of settling into a rut.

Both traps are the same failure in different clothes: the system's own output becoming its
own training data. The exploration slot is the only thing breaking the loop, and it costs
one or two slots a day out of ~8. It is not optional, and it should not be tuned away
because engagement dips slightly.

---

## New users start neutral

**No borrowed behaviour from other users** — that would be aggregate data entering the
personal layer, a violation of [Three layers](02-three-layers.md).

Instead, defaults come from **our editorial judgment**:

```
original reporting  outranks  roundups
high novelty        outranks  low
hedge-heavy         ranks     lower
```

> **That's our opinion baked into the starting position**, and the user's own feedback
> overrides it as it accumulates.

Stating it plainly matters: the cold-start ranking is an editorial position, not a neutral
one. It is defensible precisely because it is explicit and because it decays as the user's
own signal accumulates.

**Because every skip is clean, meaningful personalisation arrives within days.**
