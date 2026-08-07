# 15 — Build order

← [Rules that must not break](14-invariants.md) · [Main concept](README.md) · next → [Still open](16-open-questions.md)

Six steps. **The risk is front-loaded on purpose.**

```
Steps 1–3   where the design can be WRONG      ← the whole risk lives here
Steps 4–6   execution
```

---

## 1 — Collect and look

**100 sites, read their feeds, download articles, store them.**
**No app, no accounts, no AI.**

Then **look**:

- how many articles a day
- how many feeds broke
- how much duplication

| | |
| --- | --- |
| **Builds** | [Collect](03-collect.md), [Read](04-read.md), the `sites`/`endpoints`/`articles` tables |
| **Answers** | *How many articles a day does a 100-site list produce?* — sizes everything downstream |
| **Also answers** | *What fraction of pages carry JSON-LD?* — sizes the extraction work |
| **Done when** | You can state the daily volume and the duplication rate as numbers |

Both of those are open measurements in [Still open](16-open-questions.md), and both are
answered for free by doing this step honestly.

---

## 2 — Group and judge

**Clustering, then one AI call per story** for summary, type, novelty and hedge.

Print the day's top stories. **Read it yourself for three mornings.**

| | |
| --- | --- |
| **Builds** | [Group](05-group.md), [Judge](06-judge.md), the `stories` table |
| **Validates** | *Does novelty predict interest?* — the experiment that justifies §6 |
| **Watch** | Clustering precision. It controls the AI bill **and** the novelty signal ([Cost](13-cost.md)) |
| **Done when** | Three mornings of reading the output feels like reading something worth reading |

> **"Read it yourself for three mornings"** is the actual acceptance test. Novelty scoring
> is judged by whether the top of the list is worth a person's time — there is no offline
> metric that substitutes.

Run the 200-story novelty experiment here, before anything depends on the score.

---

## 3 — Topics

**Write ten keyword lists by hand. Run them. Read the output.**

> ***Do not move on until this is good.***
>
> If matching is bad with a carefully hand-written list, **no amount of AI expansion
> rescues it.**

| | |
| --- | --- |
| **Builds** | the matching engine — reverse index, vector recall, must/should/exclude evaluation ([Match](07-match.md)) |
| **Deliberately excludes** | the distiller. Hand-written lists isolate the matcher from the generator |
| **Done when** | Ten hand-written topics produce output you would subscribe to |

**This is the most important gate in the sequence.** It separates two failure sources that
are otherwise indistinguishable: a matcher that can't match, and a distiller that writes
bad keyword lists. Building step 4 first makes every bad result ambiguous.

---

## 4 — The distiller

**Sentence in, keyword list out.** The editable chips screen. The live preview.

| | |
| --- | --- |
| **Builds** | understand → expand → confirm ([Match](07-match.md)) |
| **Depends on** | step 3 being good, and step 1's corpus existing (the preview needs real headlines) |
| **Done when** | A stranger's sentence produces a chip list they recognise as what they meant |

Expansion is where the value is — and its quality is only measurable now that the matcher
underneath is known-good.

---

## 5 — The app

**Accounts, dashboard, cards, feedback capture. First real users.**

| | |
| --- | --- |
| **Builds** | [Deliver](08-deliver.md), the personal tables, feedback capture ([Feedback](09-feedback.md)) |
| **Note** | Capture feedback from day one even though nothing consumes it yet — step 6 needs history that only time produces |
| **Measure immediately** | **Fingerprint the first 500 signups and count distinct topics** ([Cost](13-cost.md)) |
| **Done when** | Real users have a populated dashboard in under a minute ([Journey](10-user-journey.md)) |

---

## 6 — Learning

**Personal weights, exclusion suggestions, drift detection, notifications.**

| | |
| --- | --- |
| **Builds** | the personal ranking layer, topic upkeep, the digest |
| **Depends on** | [Judge](06-judge.md)'s three axes being trustworthy — feedback generalises along novelty, story type and hedge density |
| **Traps** | position bias and collapse ([Feedback](09-feedback.md)) — build the exploration slot in from the start, not later |

---

## Why this order

> **The risk is front-loaded on purpose. Steps 1–3 are where the design can be wrong.
> Steps 4–6 are execution.**

Each early step also removes a specific way of being fooled later:

| Step | The confusion it prevents |
| --- | --- |
| 1 before 2 | Judging quality can't be assessed without knowing the volume and duplication it operates on |
| 2 before 3 | Match quality is unreadable if the stories being matched are duplicated or badly summarised |
| 3 before 4 | A bad feed could be the matcher or the distiller — hand-written lists eliminate one |
| 5 before 6 | Learning needs real feedback history; there is no way to shortcut elapsed time |

The three unvalidated premises of the project are each tested at their earliest possible
step: **volume** at 1, **novelty predicts interest** at 2, **matching works** at 3, and
**topics deduplicate** at 5. → [Still open](16-open-questions.md)
