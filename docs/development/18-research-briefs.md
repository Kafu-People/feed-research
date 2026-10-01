# 18 — Research briefs

← [Deployment](15-deployment.md) · [Dev README](README.md)

The second delivery surface. The crawler reports what publishers **published**; this reports
what people **posted**.

---

## Why it exists

The pipeline is good at trade press and bad at niches. A topic like "what does data
annotation work actually pay" lives on Reddit and in forums, and the crawler cannot go
there: Reddit's robots.txt forbids crawling, and `PoliteFetcher` obeys robots.txt by
production invariant.

Google licenses that content and indexes it. So asking Google is legitimate where crawling
it is not.

> **The line this must not cross.** `ai/gemini.py` returns an answer and a list of **links**.
> Nothing downstream fetches those links. Doing so would route around the robots.txt the
> crawler respects, using Google as the laundry. Links stay links.

---

## The shape

```
 /techtrend add <name> <prompt>     →  brief_topics row
                                          │
         09:00 local, per cadence  ───────┤
                                          ▼
                              Gemini + Google Search grounding
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    ▼                                           ▼
          the written explanation                    the same thing as tables
                    └──────────────  #techtrend-briefs  ────────┘
```

Two posts, not one. They answer different questions: understanding wants paragraphs,
deciding wants a grid. One research call produces both halves, so the second post is free.

### Three rhythms, one topic

A topic is not one question. The **window** appended to its prompt decides what it means.

| Cadence | Fires | Asks for |
| --- | --- | --- |
| daily | every day | what is NEW in the last 24 hours |
| weekly | Monday | the last 7 days, grouped |
| monthly | the 1st | the complete current overview |

Each stamps its own column (`last_run_at`, `last_weekly_at`, `last_monthly_at`) — "did we do
the weekly one yet" is unanswerable from a single timestamp. A Monday the 1st files all
three, as three jobs with three keys.

Measured on the same topic and prompt, only the window changed: the monthly question
returned 17,542 characters from 4 searches; the daily returned 1,675 from 3, opening with a
dated event rather than background. Daily is the cheap one, which is the right way round for
the one that runs 30 times a month.

---

## Commands

Only in the briefs channel — Slack offers a slash command in *every* channel, so the handler
refuses elsewhere and says where to go.

```
/techtrend list                            what is being watched
/techtrend add <name> <prompt>             start watching. Name is ONE word
/techtrend edit <name> <new prompt>        change what it asks
/techtrend remove <name>                   stop (soft delete; re-adding restores it)
/techtrend run <name> [daily|weekly|monthly]   research it now, defaults to daily
/techtrend question <your question>        ask once, save nothing
/techtrend help
```

`add` upserts; `edit` refuses a name it does not know. That difference is the point: a
mistyped name in `add` creates a second topic instead of fixing the first.

`daily`, `weekly` and `monthly` are reserved names, because `run <name> monthly` reads the
last word as a cadence.

### Thread discussion

Any reply in a brief's thread is answered, **without** a mention. The prompt says: ground
every claim in a search, never predict, and say you could not confirm something rather than
filling the gap. Asked "will DataAnnotation raise pay next year", it answers "DataAnnotation
has not announced any increases for 2027" and then gives current rates.

Off by default (`TT_BRIEF_DISCUSS_ENABLED`). A bot that answers unprompted should be a
decision, not a deploy.

---

## Setup

### 1. Gemini

Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey), then **enable
billing on that Google Cloud project**. Grounding has no free-tier quota at all: without
billing every grounded call returns 429 while plain generation on the same key succeeds.

```bash
GEMINI_API_KEY=...
TT_SLACK_BRIEF_CHANNEL=#techtrend-briefs
```

### 2. Slack app

At [api.slack.com/apps](https://api.slack.com/apps), on your existing TechTrend app:

| Where | What |
| --- | --- |
| OAuth → Bot Token Scopes | `commands`, and `groups:history` + `groups:read` if the channel is private |
| Slash Commands → Create | `/techtrend`. **Leave Request URL empty** — Socket Mode delivers it |
| Event Subscriptions → Bot events | `message.groups` (private) or `message.channels` (public), for thread discussion |
| Install App | **Reinstall.** A new scope does not apply until you do |

Usage hint for the command: `list | add | edit | remove | run | question`

Then invite the bot: `/invite @techtrend` in the briefs channel.

---

## Cost, and why the caps are on searches

Grounding is billed **per search the model chooses to run**, not per prompt — and the model
chooses. Measured on real prompts: anywhere from **2 to 15 searches** for a single question.
$14 per 1,000, with 5,000 free a month shared across the Gemini 3.x models.

So every cap counts searches, not requests:

| Setting | Default | Guards |
| --- | --- | --- |
| `TT_BRIEF_MAX_PER_DAY` | 40 | the scheduled run — about 5 topics |
| `TT_BRIEF_QUESTIONS_PER_DAY` | 10 | `/techtrend question`, the one a person fires by hand |
| `TT_BRIEF_REPLIES_PER_DAY` | 30 | thread answers — chatting is free for a human |

Three models, each where it earns its price:

| Setting | Model | Job |
| --- | --- | --- |
| `TT_GEMINI_MODEL` | `gemini-3.5-flash` | research |
| `TT_GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | when research answers 503 |
| `TT_GEMINI_WRITE_MODEL` | `gemini-3.5-flash-lite` | summaries, digest, Q&A |

Version numbers are not price order: `gemini-3.6-flash` is *cheaper* than 3.5-flash today
($0.75/$3.75 against $1.50/$9.00 per MTok) and doubles on 2027-01-01.

---

## Gates

A brief is prose a model wrote about pages nobody here fetched. It is the likeliest route
for a banned subject to reach a channel, so it gets the gates the crawled path gets, applied
to the **model's own words**:

- `block_terms` on the generated text, before anything posts
- `site_blocked` on every source, matched on the **title** — grounding returns a redirect URL
  on Google's host, so the hostname cannot tell you who the publisher is

---

## Where the code is

| File | What |
| --- | --- |
| `ai/gemini.py` | `research()` grounded, `write()` ungrounded, the house style |
| `ai/gemini_client.py` | Gemini as the writer; delegates `judge`/`distill` to Claude |
| `deliver/brief.py` | the stage: cadences, gates, both posts |
| `deliver/commands.py` | `/techtrend` |
| `deliver/discuss.py` | thread answers |
| `deliver/socket.py` | Socket Mode dispatch for events and slash commands |
