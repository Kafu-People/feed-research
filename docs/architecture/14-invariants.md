# 14 — Rules that must not break

← [What it costs](13-cost.md) · [Main concept](README.md) · next → [Build order](15-build-order.md)

Twelve invariants. **If a change violates one of these, the change is wrong — not the
rule.** They are grouped by what breaks if they're violated: a lawsuit, a churned user, or
an incoherent system.

---

## Legal

**1.** Headline + our own summary + thumbnail + link out. **Never the article body**, never
long quotes.

**2.** Summaries are **genuinely rewritten**, not lightly edited ledes.

**3.** Publisher opt-out honoured **within 24 hours**.

**4.** **Never bypass a paywall.**

**5.** **Launch outside the EU first.** The press publishers' right is unsettled there and
needs a licensing position, not an engineering fix.

| Rule | Enforced in | How |
| --- | --- | --- |
| 1 | [Data model](11-data-model.md) | `articles` stores `text_key`; the body lives in S3 and is never served |
| 2 | [Judge](06-judge.md) | Two sentences, our own words, produced by the per-story call |
| 3 | [Collect](03-collect.md) | Site-level opt-out flag with a 24h SLA on the removal path |
| 4 | [Read](04-read.md) | Metadata-only path is first-class — paywalled articles work without the body |
| 5 | [Still open](16-open-questions.md) | A launch-region decision, not a code path |

Rule 4 is cheap to honour **only because** of the JSON-LD decision in
[Read](04-read.md). Without it, the paywall rule would cost real coverage and would be
under constant pressure.

---

## Quality

**6.** **One story appears once.**

**7.** **Every number in a summary must be verified against the source.**

**8.** Rank on **tap-through and dwell**, never raw clicks — otherwise the ranking learns
that outrage works.

**9.** **Diversity caps are hard rules, not scores.**

**10.** **Never pad a short day.**

| Rule | Enforced in | Failure looks like |
| --- | --- | --- |
| 6 | [Group](05-group.md) + [Deliver](08-deliver.md) — two separate dedups | The app looks broken; fastest way to lose a user |
| 7 | [Judge](06-judge.md) — extract, normalise, require containment; drop the sentence | A confidently wrong summary — worse than no summary |
| 8 | [Feedback](09-feedback.md) — the raw click is absent from the signal table | The ranker discovers outrage |
| 9 | [Deliver](08-deliver.md) — applied after scoring, not as a term | A hot topic eats the screen |
| 10 | [Deliver](08-deliver.md) — the day is allowed to be short | Trust erodes; **and skips stop being clean negatives** |

Rules 9 and 10 share a shape with `must`/`exclude` in [Match](07-match.md): **a constraint
expressed as a penalty is a constraint a high enough score defeats.** Gates must be gates.

Rule 10 has a second, non-obvious cost when broken: it destroys the property that makes
[Feedback](09-feedback.md) learn from hundreds of users instead of hundreds of thousands.

---

## Structural

**11.** **Information flows down the three layers only.** Nothing personal writes to
anything shared.

**12.** **Nothing changes a user's topic without asking them.**

| Rule | Enforced in | Failure looks like |
| --- | --- | --- |
| 11 | [Three layers](02-three-layers.md), checkable against [Data model](11-data-model.md) | Manipulable rankings; one user's behaviour altering another's results |
| 12 | [Match](07-match.md) — suggestions are proposed, never applied | A topic that quietly changes itself is a topic the user stops trusting |

Rule 11 is verifiable by inspection: **no Shared table carries a `user_id`.**

Rule 12 has both a trust reason and a structural one — the signals driving suggestions are
personal, the topic row is shared, so auto-applying would violate rule 11 as well.

---

## How these interlock

The rules are not independent. Breaking one usually breaks another:

```
#10 never pad  ──▶  the day is finite  ──▶  skips are clean negatives
                                       ──▶  private learning is viable (§9)
                                       ──▶  #11 stays affordable

#4 no paywall bypass  ◀── made cheap by ── JSON-LD metadata path (§4)

#6 one story once  ◀── requires ── correct clustering (§5)
                                 └──▶ which also controls the AI bill (§13)

#11 layers  ──▶ no collaborative filtering ──▶ needs clean negatives ──▶ needs #10
```

**The most load-bearing rule is #10.** It looks like a UX preference and is actually the
foundation of the learning system, the honesty of the ranking, and the affordability of
private personalisation.

---

## Using this list

- **In review** — a change touching Deliver, Judge or Feedback should name which rules it
  is near and why it doesn't break them.
- **In a schema change** — check the two tests in [Data model](11-data-model.md):
  no `user_id` in Shared, and personal refinements go to
  `subscriptions.personal_excludes[]`, never `topics.exclude[]`.
- **Under growth pressure** — rules 8, 9 and 10 are the ones an engagement metric will ask
  you to relax. That request is the signal the rule is working.
