# 3 — Collect

← [Three layers](02-three-layers.md) · [Main concept](README.md) · next → [Read](04-read.md)

**Stage 1 of the pipeline.** Layer: **Shared**.

| | |
| --- | --- |
| **In** | a list of ~20,000 sites and their feed URLs |
| **Out** | new article URLs, downloaded pages |
| **Judged on** | **coverage** — the one number this stage owns |
| **Tables** | `sites`, `endpoints` ([Data model](11-data-model.md)) |

---

## The mechanism

**Every news site publishes a list of its new articles. We read those lists.**

### The two formats

- **RSS / Atom feeds** — `site.com/feed`. Most sites run several, one per section.
- **News sitemaps** — `site.com/news-sitemap.xml`. Holds the last two days of articles,
  with title and publication date already inside.

We keep a list of sites and their feed URLs. A worker checks each on a schedule. New link
appears → download that page.

That's the entire discovery mechanism. It's also what Common Crawl's news crawler has used
in production since 2016.

---

## Why not Google or Gemini

Both were checked and neither can be used.

| Option | Blocker |
| --- | --- |
| **Google Custom Search API** | Closed to new signups, shuts down 1 January 2027, capped at 10,000 queries/day |
| **Gemini grounded search** | Terms forbid storing, caching, analysing, syndicating or training on results — building a news corpus is all four |

**This isn't a limitation.** Feeds are faster, free, complete, and the publisher *wants* us
to have them. A search API would also have been the wrong shape: we need everything a site
publishes, not the top results for a query.

---

## The schedule

| Tier | Sites | Checked every |
| --- | --- | --- |
| A — major outlets | ~500 | 2 minutes |
| B — regional, specialist | ~5,000 | 10 minutes |
| C — the tail | ~15,000 | 45 minutes |

Every check sends an **ETag**, so about 90% return "nothing new" in a few hundred bytes.

```
Total load  ≈  90 req/s  (feed checks)
            +   6 req/s  (downloading actual articles)
            =  one small server
```

**Intervals adapt.** A site that publishes on every check gets checked more often; a site
that's been quiet three times in a row gets backed off. Implemented as a `next_check_at`
column, not a scheduler process — see [What runs where](12-runtime.md).

---

## Two extra inputs

| Source | Cost | Cadence | Use |
| --- | --- | --- | --- |
| **GDELT** | free | every 15 min, ~100 languages | non-English coverage, and the coverage audit below |
| **CC-NEWS** | free | archive | run **once before launch** to backfill 30 days |

**The backfill is not optional.** [Judge](06-judge.md) measures novelty against the last
30 days of coverage. Without a backfill, every story on day one looks 100% new and the
core ranking signal is meaningless until a month has passed. It is also what lets
onboarding show real headlines in ten seconds ([Match](07-match.md)).

---

## Knowing what we missed

**A dead feed and a quiet publisher look identical from the inside.**

So every night, compare our article count per site against GDELT's. Sites they saw and we
didn't means either a broken feed or a site we don't have yet. That difference becomes a
work queue.

```
        our count per site
                 vs                →  gap  →  work queue
        GDELT's count per site
```

**Coverage is the one number the collection side is judged on.** Not throughput, not
latency, not feed count — coverage. Everything downstream inherits whatever this stage
fails to see, and no amount of good ranking recovers a story that was never collected.

---

## Being a good citizen

- Honour `robots.txt`, and any publisher's request to be removed — **within 24 hours**
- Identify our crawler honestly, with a contact address
- One or two connections per site, never more
- **Never bypass a paywall**

Two of these are hard invariants — [Rules](14-invariants.md) #3 and #4. The paywall rule
costs less than it appears: [Read](04-read.md) explains why paywalled articles still work
through their JSON-LD metadata alone.

---

## Failure modes

| Symptom | Likely cause | Detection |
| --- | --- | --- |
| Site silently disappears from the corpus | Feed URL moved or broke | Nightly GDELT diff |
| Whole tier goes stale | Adaptive interval backed everything off | Watch checks/sec against tier expectations |
| Duplicate articles under different URLs | Syndication, tracking params | Canonicalise URLs; [Group](05-group.md) is the backstop |
| Publisher complains about load | Connection limit not honoured per-host | Per-host concurrency cap, not global |
