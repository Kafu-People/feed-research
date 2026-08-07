# 6 — Judge

← [Group](05-group.md) · [Main concept](README.md) · next → [Match](07-match.md)

**Stage 4 of the pipeline.** Layer: **Shared**. **This is where the product's central
claim is computed.**

| | |
| --- | --- |
| **In** | one story (a group of articles about one event) |
| **Out** | summary, story type, **novelty score**, hedge score |
| **Cost** | the main AI line — one call per story ([Cost](13-cost.md)) |
| **Tables** | `stories` ([Data model](11-data-model.md)) |

---

## One call per story

**Once per story — not once per article — one AI call produces everything.**

```
50 articles about one event  ──▶  1 AI call  ──▶  summary
                                                  story type
                                                  novelty
                                                  hedge density
```

**This is the biggest lever on running cost in the whole system.** It is the reason
[Group](05-group.md) must be right, and half of why nothing expensive scales with users.

---

## What it returns

### A summary

Two sentences, **in our own words**. Never the publisher's sentences.

This is a legal requirement, not a style preference — [Rules](14-invariants.md) #1 and #2:
headline + our own summary + thumbnail + link out, genuinely rewritten, never a lightly
edited lede.

### Story type

> original reporting · official announcement · analysis · rewrite of another outlet ·
> roundup / listicle · routine data · speculation

**Most people want the first two. Most of the volume is the last four.**

Naming the type is what lets a user turn off "analyst price targets" forever. It is also
one of the three axes along which [Feedback](09-feedback.md) generalises — without it, a
dismissal teaches nothing beyond that one article.

### Novelty — the important one

Pull out the story's facts — **entities, numbers, dates, named decisions, quotes** — and
check which of them appear anywhere in the last **30 days** of coverage on the subject.

```
80% of facts new  →  a real development
 5% of facts new  →  an echo of something already reported
```

This is what separates:

| Story | Novelty | Verdict |
| --- | --- | --- |
| *"Commerce adds four fabs to the entity list"* | high | worth reading |
| *"What Nvidia's China exposure means for investors"* | low | an echo |

**Both match the same keywords. Only one is worth reading.** No keyword system can tell
them apart — which is precisely why this stage exists.

The 30-day window is why [Collect](03-collect.md) backfills before launch: without prior
coverage, everything scores as new and the signal is dead.

### Hedge density

| Substance | Filler |
| --- | --- |
| announced · ruled · filed · banned · resigned | could · may · reportedly · sources say · analysts believe |

Things that **happened** versus things that **might**. The ratio separates substance from
filler almost for free — no model call of its own, just a lexicon over the text.

---

## The verification check

**Every number in a generated summary must appear in the source article.**

```
1. Extract numerals from summary and from source
2. Normalise them          1.2bn  ==  1,200,000,000
3. Require containment
4. A number not in the source  →  drop that sentence
```

> **A confidently wrong summary is worse than no summary.**
> This check is five lines of code and it is **not optional.**

It is [Rules](14-invariants.md) #7. Numbers are where a summariser's errors are both most
likely and most damaging — a hallucinated percentage in a financial story is the kind of
mistake that ends the product's credibility in one screenshot.

---

## One guard against over-suppression

A story can be low-novelty and still important: **the first solid confirmation of
something previously rumoured.**

> Treat a jump in **source authority** as novelty in itself — the same claim moving from
> an anonymous blog to Reuters **is** new information.

Without this guard, novelty scoring systematically buries confirmations, which are among
the most valuable stories in the corpus. The facts are unchanged; the epistemic status is
not, and that is the thing that changed.

---

## What this stage owns

Every downstream ranking input except match and freshness originates here:

```
importance = novelty + source quality + how widely covered
             − hedge penalty − story-type penalty
                 ▲                    ▲            ▲
                 │                    │            │
              §6 novelty         §6 hedge     §6 story type
```

And the axes feedback learns along ([Feedback](09-feedback.md)) are **novelty, story type
and hedge density** — all three produced here.

**If this stage is wrong, ranking and learning are both wrong**, and no amount of tuning
downstream compensates.

---

## The open risk

> **Does novelty predict interest?** Take 200 stories in one subject, have a person mark
> each interesting or not, and check whether the novelty score separates them better than
> source authority alone.

This is the experiment that validates this section. It is listed in
[Still open](16-open-questions.md) and it is the second-most consequential measurement in
the project. Run it during [Build order](15-build-order.md) step 2, before anything is
built on top of the score.
