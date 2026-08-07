# 5 — Group

← [Read](04-read.md) · [Main concept](README.md) · next → [Judge](06-judge.md)

**Stage 3 of the pipeline.** Layer: **Shared**.

| | |
| --- | --- |
| **In** | new articles with embeddings |
| **Out** | **stories** — one per real-world event, with a chosen display article |
| **Tables** | `stories`, `articles.story_id` ([Data model](11-data-model.md)) |

---

## The problem

**Fifty outlets cover one event. The user must see it once.**

---

## The mechanism

Compare each new article against articles from the **last 72 hours** that could plausibly
be related. If they're close enough, they join the same **story**. Otherwise a new story
begins.

Three signals must agree:

```
similar embedding          — the meanings match
overlapping title words    — the surface forms match
same named entities        — the actors match
```

Requiring agreement across all three is what keeps precision high. Embedding similarity
alone will happily merge two different chip-export stories from the same week.

### Choosing the display article

Each story picks one article to display, chosen by:

1. **Source quality** — authority of the outlet
2. **Originality** — the wire original beats the reprint
3. **Usable image** — a card without an image looks broken

The card shows:

```
Reuters · 2h · 14 sources
```

Tapping the source count lists who else covered it. `source_count` is a genuine shared
fact about publishing — which is why [Deliver](08-deliver.md) can use it as a "how widely
covered" ranking input without violating the layer rule ([Three layers](02-three-layers.md)).

---

## Tune for precision

**Get this wrong and the app feels broken.**

Duplicates are the fastest way to lose someone, so:

> **A missed merge is better than a wrong one.**

| Error | What the user sees | Cost |
| --- | --- | --- |
| **Missed merge** (two stories, one event) | The same event twice, from two outlets | Mildly annoying; looks like ordinary news |
| **Wrong merge** (one story, two events) | A headline whose summary is about something else, and one event **silently disappears** | The app is lying. Unrecoverable trust damage |

The asymmetry is not close. Set thresholds accordingly.

---

## Why grouping is load-bearing

Grouping is not a display convenience. Three other things depend on it:

| Depends on grouping | Why |
| --- | --- |
| [Judge](06-judge.md) cost | **One AI call per story, not per article.** 50 articles → 1 call. This is the single biggest cost lever in the system ([Cost](13-cost.md)) |
| Novelty | Facts must be compared per *event*, not per article, or every reprint reads as new |
| [Deliver](08-deliver.md) dedup | Rule "one story appears once" needs a story identity to be once *of* |

Bad grouping therefore shows up as three separate symptoms — a bloated AI bill, a novelty
score that no longer discriminates, and duplicates on the dashboard. When any one appears,
check clustering first.

---

## The 72-hour window

Wide enough to catch follow-on coverage and slow regional pickup; narrow enough that
comparison stays cheap and a genuinely new development on an old subject starts its own
story rather than being absorbed into last week's.

Note the interaction with [Judge](06-judge.md): a *new story* on an old subject is exactly
the case novelty is meant to score low. The 72-hour boundary decides whether something is
"the same event" (grouping) or "a related event with few new facts" (novelty). Both routes
end in the user seeing it once, at an honest rank.

---

## Failure modes

| Symptom | Likely cause | Where it surfaces |
| --- | --- | --- |
| Duplicates on the dashboard | Threshold too strict, or entity extraction missing | User-visible immediately |
| An event vanished | Wrong merge absorbed it into another story | Silent — audit by sampling multi-source stories |
| AI bill higher than modelled | Under-merging; stories/day above forecast | [Cost](13-cost.md) |
| Novelty scores clustered high | Under-merging: reprints counted as new events | [Judge](06-judge.md) |
| A wire story shows the reprint | Display-article selection lost originality ranking | Card shows a syndicator instead of the source |
