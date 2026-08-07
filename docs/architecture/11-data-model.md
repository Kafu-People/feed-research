# 11 — Data model

← [The user's journey](10-user-journey.md) · [Main concept](README.md) · next → [What runs where](12-runtime.md)

The schema is organised **by layer** ([Three layers](02-three-layers.md)), not by feature.
Which layer a table lives in determines who may write to it.

---

## Shared layer

*Computed once. Identical for every user, forever.*

```
sites          domain, name, tier, country, language, authority, paywall

endpoints      site_id, url, kind (feed|sitemap), next_check_at, etag

articles       url, title, text_key, published_at, image, language,
               site_id, embedding, story_id

stories        display_article_id, source_count, summary,
               story_type, novelty_score, hedge_score,
               embedding, importance, created_at
```

| Table | Written by | Notes |
| --- | --- | --- |
| `sites` | ops / discovery queue | `tier` drives check frequency; `authority` feeds importance and the novelty guard ([Judge](06-judge.md)); `paywall` tells [Read](04-read.md) to expect metadata only |
| `endpoints` | [Collect](03-collect.md) | `next_check_at` **is the scheduler** ([What runs where](12-runtime.md)); `etag` is what makes ~90% of checks near-free |
| `articles` | [Read](04-read.md) | `text_key` points at S3 — **never the body** ([Rules](14-invariants.md) #1); `story_id` assigned by [Group](05-group.md) |
| `stories` | [Group](05-group.md), [Judge](06-judge.md) | `source_count` is the "14 sources" on the card; `importance` is precomputed and identical for all users ([Deliver](08-deliver.md)) |

---

## Topic layer

*Shared between users whose lists are the same.*

```
topics         fingerprint (unique), title,
               must[], should[], exclude[], entities[],
               embedding, subscriber_count, match_rate

topic_terms    term, topic_id          -- the reverse index

matches        topic_id, story_id, match_score, matched_at
               -- kept 30 days; older is recomputable
```

| Table | Notes |
| --- | --- |
| `topics` | `fingerprint` **unique** is the deduplication mechanism — normalise, hash, collide ([Match](07-match.md)). `match_rate` powers *"about 6 a day"* on the confirm screen. `subscriber_count` is the only sanctioned aggregate ([Three layers](02-three-layers.md)) |
| `topic_terms` | The inverted index — **a search engine run backwards.** Stories are looked up *in* it, not against it |
| `matches` | The one table that grows with stories × topics. **Kept 30 days; older is recomputable** — deliberately treated as a cache, not a record |

---

## Personal layer

*One user. Reads the layers above, writes nothing outside.*

```
users          id, timezone, digest_hour, push_settings

subscriptions  user_id, topic_id, personal_excludes[]

weights        user_id, kind (type|source|keyword), key, value

seen           user_id, story_id, state, at

events         user_id, story_id, kind, at
```

| Table | Notes |
| --- | --- |
| `users` | `digest_hour` + `timezone` drive the one daily notification ([Deliver](08-deliver.md)) |
| `subscriptions` | `personal_excludes[]` is the **pressure valve**: it lets a user narrow a *shared* topic without editing it for everyone ([Match](07-match.md)) |
| `weights` | The whole personal model — `kind` ∈ type/source/keyword, matching the axes [Judge](06-judge.md) produces. A few hundred rows per user |
| `seen` | Required for the finite day and for **clean negatives** ([Feedback](09-feedback.md)); `state` distinguishes shown/opened/skipped/hidden |
| `events` | The raw log weights are derived from — keep it, because the weighting scheme will change |

---

## Where things live

| Store | Holds | Why |
| --- | --- | --- |
| **Postgres** | everything above; vectors via `pgvector` | One store, transactional, and it also runs the job queue and the scheduler ([What runs where](12-runtime.md)) |
| **Redis** | today's dashboards, seen sets, the things read constantly | The read path is the only thing that scales with users ([Cost](13-cost.md)) — cache it |
| **S3** | article text and raw HTML | Postgres stores a **key**, never the body |

Keeping raw HTML in S3 is what makes extraction improvements re-runnable without
re-crawling — worth the storage on its own.

---

## Reading the schema for layer violations

The layer rule is checkable directly against this schema:

| Check | Expected |
| --- | --- |
| Does any Shared table have a `user_id`? | **No.** Its presence would mean personal data reached the shared layer |
| Does any Personal write path touch `stories` or `topics`? | **No** — except `subscriber_count`, which counts subscriptions, not behaviour |
| Where do personal refinements go? | `subscriptions.personal_excludes[]` and `weights` — never into `topics.exclude[]` |

`topics.exclude[]` is **shared across subscribers**; `subscriptions.personal_excludes[]` is
**not**. Confusing the two is the most likely way to break
[Rules](14-invariants.md) #11 and #12 in practice.

---

## What is derivable and what is not

| Data | Recoverable if lost? |
| --- | --- |
| `matches` | **Yes** — recompute from stories and topics. Hence the 30-day retention |
| `stories.summary` / `novelty_score` | Yes, but at real AI cost — treat as expensive-to-rebuild |
| `articles` + S3 bodies | Partly — feeds and sitemaps only expose recent items; CC-NEWS covers the rest imperfectly |
| `events` / `weights` | **No.** Irreplaceable — it is the user's own history and cannot be regenerated |

Backup priority follows this table, not table size.
