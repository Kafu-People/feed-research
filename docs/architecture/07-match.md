# 7 — Match

← [Judge](06-judge.md) · [Main concept](README.md) · next → [Deliver](08-deliver.md)

**Stage 5 of the pipeline.** Layer: **Topic**.

| | |
| --- | --- |
| **In** | a user's sentence → a topic; and every new story |
| **Out** | topic rows, and `matches` rows scoring story ↔ topic |
| **Tables** | `topics`, `topic_terms`, `matches` ([Data model](11-data-model.md)) |

---

## What a topic is

**A group of keywords and rules, owned by a user, run against the news.**

```
title:     AI chip export controls

must:      at least one must appear
           AI chip · GPU · accelerator · semiconductor · H100 · Blackwell
           chip export · export control

should:    these raise the score
           tariff · sanctions · entity list · fab · foundry · TSMC · ASML

entities:  Nvidia · AMD · TSMC · China · Taiwan · US Commerce Dept

exclude:   gaming GPU review · crypto mining · graphics card deal

meaning:   <embedding of the description>
```

### Keywords *and* meaning

**Keywords alone miss the paraphrase. Meaning alone can't express "must mention Nvidia."**
Together they're precise and forgiving.

### Hard gates, not weights

> **`must` and `exclude` are hard gates, not weights.**

A user who says "not gaming GPUs" means it, and **no score should override that.** A
brilliant, novel, widely-covered gaming GPU story is still excluded. Treating exclusions
as a penalty term is the single easiest way to make a topic feel out of the user's control.

---

## Building one from a sentence

Three steps.

### 1. Understand

The model reads the sentence, pulls out the subject, the named entities, what's central
versus incidental.

### 2. Expand — *this is where the value is*

The user types "AI chips." They don't think to add:

```
H100 · Blackwell · TSMC · ASML · entity list · BIS · non-English spellings
```

> **Expansion is the difference between four results a week and fifteen a day.**

It is also what makes the topic survive contact with reality — real coverage uses the
vocabulary of the industry, not the vocabulary of the person describing their interest.

### 3. Confirm — visibly

**Never hide the keywords.**

```
┌────────────────────────────────────────────────────────┐
│  AI chip export controls                        [Edit] │
│                                                        │
│  Watching for                                          │
│  [AI chip ×] [GPU ×] [semiconductor ×] [H100 ×]        │
│  [Blackwell ×] [export control ×]           [+ add]    │
│                                                        │
│  Especially                                            │
│  [Nvidia ×] [TSMC ×] [China ×]              [+ add]    │
│                                                        │
│  Not interested in                                     │
│  [gaming GPU reviews ×] [crypto mining ×]   [+ add]    │
│                                                        │
│  ─────────────────────────────────────────────────     │
│  47 stories in the last 7 days · about 6 a day         │
│                                                        │
│  Nvidia cleared to resume H20 sales to China    2h     │
│  ASML says licence rules cut Q3 China revenue   6h     │
│  Commerce adds four Chinese fabs to list        1d     │
│                                                 [Save] │
└────────────────────────────────────────────────────────┘
```

Three things this screen does that a text box can't:

1. **Shows what we understood** — a misreading is caught in five seconds, not after a week
   of bad results.
2. **Shows the rate** — *"about 6 a day"* tells them immediately if it's too broad or too
   narrow, **before** it's wrong.
3. **Shows real stories instantly** — because the corpus already exists
   ([Collect](03-collect.md) backfill). Typed sentence to real headlines in about ten
   seconds.

### Ambiguity

**If the description is ambiguous, ask one question with buttons.**

> *"Apple" — the company or the fruit?*

Unresolved ambiguity becomes a bad feed the user can't diagnose. One button press at
creation time is cheaper than a week of wrong results and a churned user.

---

## How matching runs

The obvious approach doesn't work: checking every topic against every story is **millions
of comparisons a day.**

**So we index the topics, not just the stories.** For each new story:

```
1. Look up the story's words in an index of topic keywords
   → the few hundred topics containing at least one of them

2. Vector search the story against topic meanings, top ~200
   → topics that mean the same thing without sharing words

3. Evaluate only that union — hundreds, not millions
   Apply must / should / entity / exclude properly. Score.

4. Write a match row for anything above the topic's floor
```

> **This is the same machinery as a search engine, run backwards.**

Documents arrive continuously and queries are stored — so the queries get the inverted
index (`topic_terms`) and the vector index, and each document is run against them. Cost
therefore scales with **stories/day**, not with topics × stories ([Cost](13-cost.md)).

Steps 1 and 2 are **recall** — cheap, approximate, allowed to over-return. Step 3 is
**precision** — the expensive, exact evaluation, run on a bounded candidate set. Keeping
`must`/`exclude` out of step 1 and 2 is deliberate: gates are applied where the full rule
is available, not approximated by the index.

---

## Topics deduplicate

Many users describe the same thing. **Normalise** a topic — lowercase, sort, resolve
entities — and **hash** it. Identical hashes are **one topic row with many subscribers.**

```
10,000 people typing some version of "AI news"
              ↓  fingerprint
        a handful of distinct topics
              ↓
   one matching job, ten thousand readers
```

This is the second of the two decisions that make the economics work ([Cost](13-cost.md)),
and it is the property that discovery is built on ([Journey](10-user-journey.md)):
*"People following this also follow…"* comes free from `subscriber_count`.

> **It is also the biggest unvalidated assumption in the system.** If a million users
> produce 4M distinct topics instead of ~300k, matching cost rises sharply and the design
> needs revisiting. The measurement costs one short script —
> [Still open](16-open-questions.md).

---

## Keeping topics alive

**A topic written in January doesn't know about a chip announced in June.**

| Mechanism | Example |
| --- | --- |
| **Weekly term suggestions** | *Add "Blackwell"? It appeared in 12 stories you opened.* |
| **Drift detection** | *This has been quiet for 9 days. Broaden it?* |
| **Learned exclusions** | *You've hidden 3 stories about gaming benchmarks. Exclude those?* |

> All **proposed, never applied silently.** A topic that quietly changes itself is a topic
> the user stops trusting.

This is [Rules](14-invariants.md) #12, and it has a structural reason as well as a trust
reason: the signals driving these suggestions are **personal**, and the topic row is
**shared** between subscribers. Auto-applying them would let one user's behaviour rewrite
another's topic — a direct violation of [Three layers](02-three-layers.md).

Personal-only refinements live in `subscriptions.personal_excludes[]`, which is the
sanctioned place for "just for me" adjustments to a shared topic.
