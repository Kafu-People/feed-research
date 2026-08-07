# 10 — The user's journey

← [Feedback](09-feedback.md) · [Main concept](README.md) · next → [Data model](11-data-model.md)

What the architecture looks like from the outside. Every step here is a claim the system
must be able to keep.

---

## First minute

```
1. Sign up. Empty account.

2. "What do you want to follow?"   →  one text box

3. Types a sentence.

4. ~2 seconds: keywords built and shown as editable chips,
   with a 7-day count and three real headlines.

5. Adjusts. Saves.

6. Repeat — two to four topics is typical.

7. Dashboard is full. Immediately.
```

> **Under a minute from install to a real, personal, populated dashboard.**
> No list, no waiting, no empty state.

### What each step costs the architecture

| Step | Requires | From |
| --- | --- | --- |
| 2 — one text box | No taxonomy anywhere in the system | [The idea](01-the-idea.md) |
| 4 — ~2 seconds | Distiller fast enough to be interactive | [Match](07-match.md) |
| 4 — a 7-day count | A corpus that already exists at signup | [Collect](03-collect.md) backfill |
| 4 — three real headlines | Matching runnable on demand, not just on ingest | [Match](07-match.md) |
| 7 — full immediately | Stories already judged and ranked before this user existed | [Judge](06-judge.md) |

**The empty state is solved by the backfill, not by the UI.** This is the clearest case of
an infrastructure decision buying a product outcome: CC-NEWS 30-day backfill is what makes
step 4 possible, and step 4 is what makes onboarding work.

---

## Discovery, without a taxonomy

Afterwards, because topics deduplicate ([Match](07-match.md)), we can offer:

> *People following this also follow:* **Semiconductor supply chain** *(2,341)*

**Discovery without a taxonomy — driven by what people actually asked for.**

This is legitimate under [Three layers](02-three-layers.md) because `subscriber_count` is
a count of **stated intent** living in the Topic layer, not a behavioural signal, and it
never enters ranking.

Note the ordering: deduplication is adopted for **cost** reasons, and discovery falls out
of it for free. The taxonomy is emergent — it is whatever users described, normalised.

---

## Every day after

```
Notification at their hour
        ↓
Open the dashboard
        ↓
Cards from all topics, mixed, best first, each labelled
        ↓
Read / tap through / skip / hide
        ↓
"That's today."   →   more, if they want it
        ↓
Their weights shift. Tomorrow is a little more theirs.
```

### The loop, annotated

| Moment | System behaviour | Document |
| --- | --- | --- |
| Notification at their hour | One digest; breaking capped at two; ignoring yields **fewer** | [Deliver](08-deliver.md) |
| Cards mixed, best first | Importance is absolute across topics | [Deliver](08-deliver.md) |
| Each labelled | The user can always see *why* a card is there | [Match](07-match.md) |
| Skip | A **clean negative** — only possible because the set is finite | [Feedback](09-feedback.md) |
| "That's today." | The bottom exists; the day is allowed to be short | [Deliver](08-deliver.md) |
| Weights shift | Personal layer only; the story never changes | [Three layers](02-three-layers.md) |

---

## The two promises this journey makes

**1. Nothing here was chosen for you.** The topic came from the user's sentence, the
keywords are visible and editable, the matched keyword is shown on every card, and no
suggestion is applied without being accepted ([Rules](14-invariants.md) #12).

**2. When it's done, it's done.** The day ends. Ignoring notifications reduces them.
A quiet day is short. The product does not compete for attention it hasn't earned.

Both promises are enforced by invariants rather than by intent — which is the reason
[Rules that must not break](14-invariants.md) exists as a separate list.
