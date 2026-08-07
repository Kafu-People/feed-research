# 1 — The idea

← [Main concept](README.md) · next → [The three layers](02-three-layers.md)

Three things make this different from every other news app. Each one has consequences
that reach through the whole system, so they are stated here once and referenced
everywhere else.

---

## 1. The user writes a sentence, not a topic choice

No list to pick from. They describe what they care about —

> *"AI chips and export restrictions, especially Nvidia and China"*

— and we turn that into a group of keywords that searches the news.

**A topic is a lens the user owns, not a category we invented.**

### What this forces

| Consequence | Where it lands |
| --- | --- |
| We need a distiller: sentence in, keyword list out | [Match](07-match.md) |
| The keywords must be **visible and editable** — never hidden | [Match](07-match.md) |
| Matching must run topic-indexed, not story-by-topic | [Match](07-match.md) |
| Identical topics must collapse to one row, or cost explodes | [Cost](13-cost.md) |
| Onboarding is a text box and a preview, not a category grid | [Journey](10-user-journey.md) |

### Why not a topic list

A list is the product deciding what exists. Anything not on it is unreachable, and
anything on it is a compromise between all users. A sentence has no such ceiling — and
because topics deduplicate afterward, we get the operational benefit of a small taxonomy
*without* imposing one.

---

## 2. We rank by what's new, not by what's loud

**Interest isn't a property a story has on its own.** The sixth article this week about
the same thing is boring even though it looks identical to the first.

So we measure how much of a story is *actually new* against everything published on the
subject in the last month, and rank on that.

```
"Commerce adds four fabs to the entity list"        →  80% new facts  →  a development
"What Nvidia's China exposure means for investors"  →   5% new facts  →  an echo
```

Both match the same keywords. Only one is worth reading.

### What this forces

| Consequence | Where it lands |
| --- | --- |
| We need a **30-day corpus**, not a live stream | [Collect](03-collect.md) |
| Articles must be grouped per event before judging | [Group](05-group.md) |
| Facts must be extractable and comparable | [Judge](06-judge.md) |
| Feedback gets axes to generalise along | [Feedback](09-feedback.md) |
| The day can end — there is a finite set of *new* things | [Deliver](08-deliver.md) |

### The risk this carries

This is the **unvalidated premise of the project.** It is plausible and it is not proven.
The experiment that tests it is defined in [Still open](16-open-questions.md): take 200
stories in one subject, have a person mark each interesting or not, and check whether the
novelty score separates them better than source authority alone.

If novelty does not predict interest, section 6 and the ranking built on it need
rethinking. Nothing else in the architecture changes.

---

## 3. Feedback is private

What a user hides or opens changes **their own ordering and nobody else's.** The story
itself never changes.

### What this forces

| Consequence | Where it lands |
| --- | --- |
| A strict layer rule: personal never writes to shared | [Three layers](02-three-layers.md) |
| New users start from editorial defaults, not borrowed behaviour | [Feedback](09-feedback.md) |
| Coordinated downvoting cannot move anything | [Three layers](02-three-layers.md) |
| One user's model going strange affects one person | [Three layers](02-three-layers.md) |

### What it costs

We give up collaborative filtering — the "users like you also read" signal that most
recommenders lean on. The compensation is that **every skip is a clean negative**
([Feedback](09-feedback.md)): with a finite daily set the user has seen everything, so
learning that would normally need hundreds of thousands of users needs hundreds.

---

## The three together

```
sentence, not a list        →  the topic is the user's
new, not loud               →  the ranking is honest
private feedback            →  the system is unmanipulable
```

They are not independent features. The sentence produces topics that deduplicate, which
makes judging affordable; judging produces novelty, which makes ranking honest; honest
ranking makes a finite day possible; a finite day makes skips clean; clean skips make
private personalisation learn fast enough to work at all.

**Remove any one and the other two get materially worse.**
