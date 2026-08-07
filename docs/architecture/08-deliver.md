# 8 — Deliver

← [Match](07-match.md) · [Main concept](README.md) · next → [Feedback](09-feedback.md)

**Stage 6 of the pipeline.** Reads all three layers, writes none of them.

| | |
| --- | --- |
| **In** | matched stories + the user's personal weights |
| **Out** | one ordered dashboard, and notifications |
| **Runs in** | the API, cached in Redis ([What runs where](12-runtime.md)) |

---

## One home dashboard

**Cards from all of the user's topics, mixed together, ordered by what matters most.**
Not sections to navigate — **one screen, one ordered list.**

Each card carries a small **topic label**, so the user can see why it's there. Tapping the
label filters the dashboard to just that topic.

> **But the ordering itself ignores topic boundaries entirely.**

---

## How a card is scored

```
importance    novelty + source quality + how widely covered
              − hedge penalty − story-type penalty

× match       how well it fit that topic's keywords

× freshness   decaying — but at different speeds by subject.
              A markets story is stale in hours; a research
              result is fine three days later.

× personal    that user's weights: story types, sources, keywords
```

Note where each factor comes from — the layer rule is visible in the formula itself:

| Factor | Layer | Computed in |
| --- | --- | --- |
| importance | **Shared** | [Judge](06-judge.md) + [Group](05-group.md) |
| match | **Topic** | [Match](07-match.md) |
| freshness | **Shared** | subject-dependent decay |
| personal | **Personal** | [Feedback](09-feedback.md) |

`importance` is stored once on the story and is identical for everyone. Only the last
factor differs per user — which is exactly the promise of
[Three layers](02-three-layers.md): *the same story looks the same to everyone; only the
ordering differs.*

### Importance is absolute

> **A big development in a minor topic outranks a routine story in a major one.**

That's correct. Importance is absolute, not per-topic. Normalising within topics would
guarantee every topic gets screen time regardless of whether anything happened in it —
which is padding by another name.

### Freshness decays at different speeds

A markets story is stale in hours; a research result is fine three days later. A single
global half-life is wrong for both. Decay rate is a property of the subject, not of the
system.

---

## Then three rules

### Deduplicate

A story matching two topics appears **once**, at its **best** score, labelled with both.

> **There's no second place for it to show up.**

[Rules](14-invariants.md) #6. Note this is the *second* dedup in the pipeline —
[Group](05-group.md) removes duplicate *articles*; this removes duplicate *placements*.

### Cap

**No single topic or single source can fill the screen.**

> **Diversity caps are hard rules, not scores** — [Rules](14-invariants.md) #9.

The same reasoning as `must`/`exclude` in [Match](07-match.md): a cap expressed as a
penalty is a cap that a sufficiently high score defeats, which means it isn't a cap.

### Don't pad

**A quiet day is allowed to be quiet.** If there are seven good things, show seven.

> **Filler is how you teach someone to stop trusting the dashboard.**

[Rules](14-invariants.md) #10. Padding also destroys the property that
[Feedback](09-feedback.md) depends on: if the set contains filler the user was never meant
to want, a skip stops being a clean negative.

---

## The bottom exists

Below the cards: a line that says the day is done, then more for whoever wants it.

> **Finishing is a feature. Everyone else optimises endless scroll.**

The finite day is not only a UX stance. It is what makes **every skip a clean negative**
([Feedback](09-feedback.md)) — with an endless feed you cannot distinguish "didn't see it"
from "rejected it," and the entire fast-learning argument collapses.

---

## Notifications

| | |
| --- | --- |
| **Daily digest** | one, at the user's chosen hour (`users.digest_hour`) |
| **Breaking alerts** | capped at **two a day**, only for stories far above their normal threshold |

> **Ignore them and you get fewer, not more.**

The inverted response is the point: engagement-maximising systems escalate when ignored.
Treating a non-response as a signal to back off is the same principle as never padding —
the product is willing to ask for less attention when it has less to say.

---

## What Deliver must never do

| Temptation | Which rule it breaks |
| --- | --- |
| Fill a short day with the next-best stories | #10 don't pad |
| Let a hot topic take six of ten slots because it scored well | #9 caps are hard rules |
| Show a story under both its topics | #6 one story appears once |
| Rank on raw clicks | #8 rank on tap-through and dwell — otherwise ranking learns that outrage works |
| Normalise importance within a topic | Importance is absolute |
