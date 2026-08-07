# TechTrend — Architecture

A news app. The user describes what they want to follow in their own words. Every day
they open one dashboard and see the things worth knowing, ranked, with no duplicates.

This is the complete reference. It replaces all earlier drafts.

---

## Contents

1. [The idea](#1-the-idea)
2. [The three layers](#2-the-three-layers)
3. [Collect](#3-collect)
4. [Read](#4-read)
5. [Group](#5-group)
6. [Judge](#6-judge)
7. [Match](#7-match)
8. [Deliver](#8-deliver)
9. [Feedback](#9-feedback)
10. [The user's journey](#10-the-users-journey)
11. [Data model](#11-data-model)
12. [What runs where](#12-what-runs-where)
13. [What it costs](#13-what-it-costs)
14. [Rules that must not break](#14-rules-that-must-not-break)
15. [Build order](#15-build-order)
16. [Still open](#16-still-open)

---

## 1. The idea

Three things make this different from every other news app.

**The user writes a sentence, not a topic choice.** No list to pick from. They describe
what they care about — *"AI chips and export restrictions, especially Nvidia and
China"* — and we turn that into a group of keywords that searches the news. A topic is a
lens the user owns, not a category we invented.

**We rank by what's new, not by what's loud.** Interest isn't a property a story has on
its own. The sixth article this week about the same thing is boring even though it looks
identical to the first. So we measure how much of a story is *actually new* against
everything published on the subject in the last month, and rank on that.

**Feedback is private.** What a user hides or opens changes their own ordering and
nobody else's. The story itself never changes.

---

## 2. The three layers

Everything in the system belongs to one of three layers, and **information only flows
downward.** This is the rule that keeps the system predictable.

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

Three things this buys:

- **Predictable.** The same story looks the same to everyone. Only the ordering differs.
- **Unmanipulable.** No amount of coordinated downvoting can move a shared value,
  because no user writes to the shared layer.
- **Stable.** Each user's model is independent, so one going strange affects one person.

---

## 3. Collect

**Every news site publishes a list of its new articles. We read those lists.**

### The two formats

- **RSS / Atom feeds** — `site.com/feed`. Most sites run several, one per section.
- **News sitemaps** — `site.com/news-sitemap.xml`. Holds the last two days of articles,
  with title and publication date already inside.

We keep a list of sites and their feed URLs. A worker checks each on a schedule. New
link appears → download that page.

That's the entire discovery mechanism. It's also what Common Crawl's news crawler has
used in production since 2016.

### Why not Google or Gemini

Both were checked and neither can be used.

- **Google Custom Search API** — closed to new signups, shuts down 1 January 2027, and
  capped at 10,000 queries a day anyway.
- **Gemini grounded search** — the terms forbid storing, caching, analysing, syndicating
  or training on results. Building a news corpus is all four of those.

This isn't a limitation. Feeds are better: faster, free, complete, and the publisher
wants us to have them.

### The schedule

| Tier | Sites | Checked every |
| --- | --- | --- |
| A — major outlets | ~500 | 2 minutes |
| B — regional, specialist | ~5,000 | 10 minutes |
| C — the tail | ~15,000 | 45 minutes |

Every check sends an ETag, so about 90% return "nothing new" in a few hundred bytes.
Total load is roughly **90 requests per second**, plus ~6/second downloading actual
articles. One small server.

Intervals adapt: a site that publishes on every check gets checked more often, a site
that's been quiet three times in a row gets backed off.

### Two extra inputs

- **GDELT** — free, every 15 minutes, ~100 languages. Use for non-English coverage.
- **CC-NEWS** — free archive. Use once before launch to backfill 30 days, so the app
  isn't empty on day one.

### Knowing what we missed

A dead feed and a quiet publisher look identical from the inside. So every night,
compare our article count per site against GDELT's. Sites they saw and we didn't means
either a broken feed or a site we don't have yet. That difference becomes a work queue.

**Coverage is the one number the collection side is judged on.**

### Being a good citizen

- Honour `robots.txt`, and any publisher's request to be removed — within 24 hours
- Identify our crawler honestly, with a contact address
- One or two connections per site, never more
- Never bypass a paywall

---

## 4. Read

For each downloaded page, extract: title, text, publication date, author, image,
language.

**Most of it is already structured.** Publishers embed a `JSON-LD NewsArticle` block
because Google requires it — headline, date, author, image, section. Take that first.
Only fall back to text extraction (`trafilatura`) for the article body.

This matters: **for matching and ranking we often don't need the body at all.** Which
means paywalled articles still work — we get the headline, date and image legitimately,
and send the reader to the publisher.

Then compute an **embedding** — a numeric fingerprint of the meaning. This is what makes
grouping and keyword-free matching possible.

---

## 5. Group

Fifty outlets cover one event. The user must see it **once**.

Compare each new article against articles from the last 72 hours that could plausibly be
related. If they're close enough — similar embedding, overlapping title words, same
named entities — they join the same **story**. Otherwise a new story begins.

Each story picks one article to display, chosen by source quality, originality (the wire
original beats the reprint) and whether it has a usable image.

The card shows: **"Reuters · 2h · 14 sources."** Tapping the source count lists who else
covered it.

**Get this wrong and the app feels broken.** Duplicates are the fastest way to lose
someone, so tune clustering for precision — a missed merge is better than a wrong one.

---

## 6. Judge

**Once per story — not once per article — one AI call produces everything.**

Fifty articles about one event → one call. This is the biggest lever on running cost in
the whole system.

It returns:

**A summary.** Two sentences, in our own words. Never the publisher's sentences.

**Story type.**

> original reporting · official announcement · analysis · rewrite of another outlet ·
> roundup / listicle · routine data · speculation

Most people want the first two. Most of the volume is the last four. Naming the type is
what lets a user turn off "analyst price targets" forever.

**Novelty — the important one.** Pull out the story's facts: entities, numbers, dates,
named decisions, quotes. Check which of them appear anywhere in the last 30 days of
coverage on the subject.

> 80% of facts new → a real development
> 5% of facts new → an echo of something already reported

This is what separates *"Commerce adds four fabs to the entity list"* from *"What
Nvidia's China exposure means for investors."* Both match the same keywords. Only one is
worth reading.

**Hedge density.** *Announced, ruled, filed, banned, resigned* describe things that
happened. *Could, may, reportedly, sources say, analysts believe* describe things that
might. The ratio separates substance from filler almost for free.

### The verification check

Every number in a generated summary must appear in the source article. Extract the
numerals from both, normalise them (`1.2bn` = `1,200,000,000`), and require containment.
A number that isn't in the source gets the sentence dropped.

**A confidently wrong summary is worse than no summary.** This check is five lines of
code and it is not optional.

### One guard against over-suppression

A story can be low-novelty and still important: the first *solid confirmation* of
something previously rumoured. So treat a jump in source authority as novelty in itself
— the same claim moving from an anonymous blog to Reuters **is** new information.

---

## 7. Match

### What a topic is

A group of keywords and rules, owned by a user, run against the news.

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

**Keywords and meaning both matter.** Keywords alone miss the paraphrase. Meaning alone
can't express "must mention Nvidia." Together they're precise and forgiving.

**`must` and `exclude` are hard gates, not weights.** A user who says "not gaming GPUs"
means it, and no score should override that.

### Building one from a sentence

Three steps.

**Understand.** The model reads the sentence, pulls out the subject, the named entities,
what's central versus incidental.

**Expand.** *This is where the value is.* The user types "AI chips." They don't think to
add H100, Blackwell, TSMC, ASML, entity list, BIS, or the non-English spellings.
Expansion is the difference between four results a week and fifteen a day.

**Confirm — visibly.** Never hide the keywords.

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

1. **Shows what we understood** — a misreading is caught in five seconds, not after a
   week of bad results.
2. **Shows the rate** — "about 6 a day" tells them immediately if it's too broad or too
   narrow, *before* it's wrong.
3. **Shows real stories instantly** — because the corpus already exists. Typed sentence
   to real headlines in about ten seconds.

**If the description is ambiguous, ask one question with buttons.** *"Apple" — the
company or the fruit?* Unresolved ambiguity becomes a bad feed the user can't diagnose.

### How matching runs

The obvious approach doesn't work: checking every topic against every story is millions
of comparisons a day.

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

This is the same machinery as a search engine, run backwards.

### Topics deduplicate

Many users describe the same thing. Normalise a topic — lowercase, sort, resolve
entities — and hash it. Identical hashes are **one topic row with many subscribers**.

Ten thousand people typing some version of "AI news" collapse to a handful of distinct
topics. One matching job, ten thousand readers.

### Keeping topics alive

A topic written in January doesn't know about a chip announced in June.

- **Weekly term suggestions** — *Add "Blackwell"? It appeared in 12 stories you opened.*
- **Drift detection** — *This has been quiet for 9 days. Broaden it?*
- **Learned exclusions** — *You've hidden 3 stories about gaming benchmarks. Exclude
  those?*

All **proposed, never applied silently.** A topic that quietly changes itself is a topic
the user stops trusting.

---

## 8. Deliver

**One home dashboard.** Cards from all of the user's topics, mixed together, ordered by
what matters most. Not sections to navigate — one screen, one ordered list.

Each card carries a small **topic label**, so the user can see why it's there. Tapping
the label filters the dashboard to just that topic. But the ordering itself ignores
topic boundaries entirely.

### How a card is scored

```
importance    novelty + source quality + how widely covered
              − hedge penalty − story-type penalty

× match       how well it fit that topic's keywords

× freshness   decaying — but at different speeds by subject.
              A markets story is stale in hours; a research
              result is fine three days later.

× personal    that user's weights: story types, sources, keywords
```

**A big development in a minor topic outranks a routine story in a major one.** That's
correct — importance is absolute, not per-topic.

### Then three rules

**Deduplicate.** A story matching two topics appears **once**, at its best score,
labelled with both. There's no second place for it to show up.

**Cap.** No single topic or single source can fill the screen.

**Don't pad.** A quiet day is allowed to be quiet. If there are seven good things, show
seven. Filler is how you teach someone to stop trusting the dashboard.

### The bottom exists

Below the cards: a line that says the day is done, then more for whoever wants it.
Finishing is a feature. Everyone else optimises endless scroll.

### Notifications

One daily digest at the user's chosen hour. Breaking alerts capped at two a day, only
for stories far above their normal threshold. Ignore them and you get **fewer**, not
more.

---

## 9. Feedback

Every action writes to **that user's row only.** Never to the story. Never to anyone
else's dashboard.

### What we collect, strongest first

| Signal | Strength |
| --- | --- |
| Tapped through to the publisher | strongest — they left the app for it |
| Saved or shared | strong |
| Read the expanded card fully | good — dwell relative to summary length |
| Expanded it at all | moderate |
| Scrolled past fast | negative |
| Skipped entirely | negative, and **clean** |
| Dismissed with a reason | most valuable, rarest |

**Why "skipped" is clean.** In an endless feed you can't tell "didn't see it" from
"rejected it." With a finite daily set, the user has seen everything. Every skip is a
real negative. That means learning from hundreds of users what would normally need
hundreds of thousands.

### Natural moments, not a rating chore

**End of day, one tap.** After the last card: *"Best one today?"* It arrives at the
natural stopping point, and one tap ranks the whole set.

**Dismiss with a reason.** Swiping shows a brief toast: `Hidden · Why?` Most ignore it.
The ones who tap give the most valuable data in the system — because a thumbs-down means
at least five different things, and conflating them teaches the wrong lesson.

**Feedback on the keyword.** Unique to this design: a card shows which keyword matched
it, so the user can act on the keyword rather than the article. *"Less about price
targets."* That edits the topic directly, and the user sees exactly what changed.

### How the signals become learning

Feedback alone teaches nothing generalisable — one thumbs-down on one article is one
data point. What makes it generalise is being able to **describe** what that article was:
analysis rather than reporting, low novelty, hedge-heavy, from this source, matched by
this keyword.

**Novelty, story type and hedge density are the axes feedback gets learned along.**
Without them you're memorising individual articles. With them, one dismissal generalises
to a thousand future ones.

### What the personal layer holds

Small — a few hundred numbers per user, fitting in one row:

- a weight per story type
- a weight per source
- a weight per keyword in their own topics
- their seen list

### Two traps

**Position bias.** Cards shown first get engaged with regardless of quality. Train
naively and the model learns "position 1 is good" and locks in whatever it already
believed. Correct for it, or shuffle a slot occasionally.

**Collapse.** A ranker trained only on what it already showed narrows fast. Reserve a
slot or two a day for genuine uncertainty — things the model can't predict a response
to. That's how it keeps learning instead of settling into a rut.

### New users start neutral

No borrowed behaviour from other users — that would be aggregate data entering the
personal layer.

Instead, defaults come from **our editorial judgment**: original reporting outranks
roundups, high novelty outranks low, hedge-heavy ranks lower. That's our opinion baked
into the starting position, and the user's own feedback overrides it as it accumulates.

Because every skip is clean, meaningful personalisation arrives within days.

---

## 10. The user's journey

### First minute

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

**Under a minute from install to a real, personal, populated dashboard.** No list, no
waiting, no empty state.

Afterwards, because topics deduplicate, we can offer: *People following this also
follow: **Semiconductor supply chain** (2,341)*. Discovery without a taxonomy — driven by
what people actually asked for.

### Every day after

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

---

## 11. Data model

### Shared layer

```
sites          domain, name, tier, country, language, authority, paywall
endpoints      site_id, url, kind (feed|sitemap), next_check_at, etag

articles       url, title, text_key, published_at, image, language,
               site_id, embedding, story_id

stories        display_article_id, source_count, summary,
               story_type, novelty_score, hedge_score,
               embedding, importance, created_at
```

### Topic layer

```
topics         fingerprint (unique), title,
               must[], should[], exclude[], entities[],
               embedding, subscriber_count, match_rate

topic_terms    term, topic_id          -- the reverse index

matches        topic_id, story_id, match_score, matched_at
               -- kept 30 days; older is recomputable
```

### Personal layer

```
users          id, timezone, digest_hour, push_settings
subscriptions  user_id, topic_id, personal_excludes[]
weights        user_id, kind (type|source|keyword), key, value
seen           user_id, story_id, state, at
events         user_id, story_id, kind, at
```

### Where things live

- **Postgres** — everything above. Vectors via `pgvector`.
- **Redis** — today's dashboards, seen sets, the things read constantly.
- **S3** — article text and raw HTML. Postgres stores a key, never the body.

---

## 12. What runs where

```
       phone / web
            │
            ▼
      ┌──────────┐
      │   API    │   reads, ranks, returns
      └────┬─────┘
           │
   ┌───────▼────────────────────┐
   │  Postgres · Redis · S3     │
   └───────▲────────────────────┘
           │
      ┌────┴─────┐
      │ workers  │   collect · read · group · judge · match
      └──────────┘
```

**Two things to run: the API and the workers.** Same code, different command. Both scale
by adding copies.

No message broker — jobs live in a Postgres table, claimed with `SELECT ... FOR UPDATE
SKIP LOCKED`. No scheduler process — every schedule is a `next_check_at` column.

**Python** for the backend. **React Native** for the app.

---

## 13. What it costs

| | Scales with | Notes |
| --- | --- | --- |
| Collecting | number of sites | ~90 req/s. Small. |
| Downloading | articles/day | ~6 req/s |
| Embeddings | articles/day | cheap, batched |
| **Judging** | **stories/day** | **the main AI cost — one call per story** |
| Matching | stories/day | index lookups |
| Serving | users | the cheapest line |

**Nothing expensive scales with the number of users.** Doubling the audience roughly
doubles only serving. Collecting and judging barely move.

That's the whole business case, and it comes from two decisions: judge once per story
rather than per article, and share topics between users who describe the same thing.

---

## 14. Rules that must not break

### Legal

1. Headline + our own summary + thumbnail + link out. **Never the article body**, never
   long quotes.
2. Summaries are genuinely rewritten, not lightly edited ledes.
3. Publisher opt-out honoured within 24 hours.
4. Never bypass a paywall.
5. **Launch outside the EU first.** The press publishers' right is unsettled there and
   needs a licensing position, not an engineering fix.

### Quality

6. One story appears once.
7. Every number in a summary must be verified against the source.
8. Rank on tap-through and dwell, **never raw clicks** — otherwise the ranking learns
   that outrage works.
9. Diversity caps are hard rules, not scores.
10. Never pad a short day.

### Structural

11. Information flows down the three layers only. Nothing personal writes to anything
    shared.
12. Nothing changes a user's topic without asking them.

---

## 15. Build order

**1 — Collect and look.** 100 sites, read their feeds, download articles, store them. No
app, no accounts, no AI. Then look: how many articles a day, how many feeds broke, how
much duplication.

**2 — Group and judge.** Clustering, then one AI call per story for summary, type,
novelty and hedge. Print the day's top stories. **Read it yourself for three mornings.**

**3 — Topics.** Write ten keyword lists by hand. Run them. Read the output. *Do not move
on until this is good* — if matching is bad with a carefully hand-written list, no amount
of AI expansion rescues it.

**4 — The distiller.** Sentence in, keyword list out. The editable chips screen. The live
preview.

**5 — The app.** Accounts, dashboard, cards, feedback capture. First real users.

**6 — Learning.** Personal weights, exclusion suggestions, drift detection, notifications.

The risk is front-loaded on purpose. Steps 1–3 are where the design can be wrong. Steps
4–6 are execution.

---

## 16. Still open

### To decide

| | Recommendation |
| --- | --- |
| Launch region | Outside the EU |
| Money | Subscription, not ads. Ads reward exactly the behaviour rules 8–10 prevent. |
| Domain at launch | Pick one — tech, or finance. "Everything" is several products with different freshness rules and source lists. |
| Platform | One first. Not both stores at once. |

### To measure

**Do topics deduplicate?** Fingerprint the first 500 real signups and count distinct
values. If a million users produce 300k distinct topics this works comfortably; if they
produce 4M, matching cost rises sharply and the design needs revisiting. *This is the
most important measurement in the project, and it costs one short script.*

**Does novelty predict interest?** Take 200 stories in one subject, have a person mark
each interesting or not, and check whether the novelty score separates them better than
source authority alone. This is the experiment that validates §6.

**What fraction of pages carry JSON-LD?** Sample 500. Decides how much extraction work
exists.

**How many articles a day does a 100-site list produce?** Count it. Sizes everything
downstream.
