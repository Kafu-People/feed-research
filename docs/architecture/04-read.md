# 4 — Read

← [Collect](03-collect.md) · [Main concept](README.md) · next → [Group](05-group.md)

**Stage 2 of the pipeline.** Layer: **Shared**.

| | |
| --- | --- |
| **In** | a downloaded HTML page |
| **Out** | title, text, publication date, author, image, language, **embedding** |
| **Tables** | `articles` ([Data model](11-data-model.md)) |

---

## Take the structured data first

**Most of it is already structured.** Publishers embed a `JSON-LD NewsArticle` block
because Google requires it — headline, date, author, image, section.

```
1. Parse JSON-LD NewsArticle   →  headline, date, author, image, section
2. Fall back to trafilatura    →  article body only
```

Only fall back to text extraction for the article **body**. Everything else should come
from the publisher's own markup, which is more accurate than any heuristic and does not
break when a site redesigns.

> **Open question:** what fraction of pages actually carry JSON-LD? Sample 500 to size the
> extraction work. → [Still open](16-open-questions.md)

---

## The consequence that matters

**For matching and ranking we often don't need the body at all.**

[Match](07-match.md) works largely on title, entities and embedding. [Deliver](08-deliver.md)
shows a headline, our summary and a thumbnail. So:

> **Paywalled articles still work.** We get the headline, date and image legitimately from
> the publisher's own metadata, and send the reader to the publisher.

This is what makes [Rules](14-invariants.md) #4 — *never bypass a paywall* — cheap to
honour rather than a painful concession. A paywalled article is a first-class citizen of
the corpus.

It also constrains what [Judge](06-judge.md) can do: for a story whose sources are all
paywalled, novelty and summary must be derivable from headlines and metadata, with lower
confidence than a story with full text.

---

## The embedding

Then compute an **embedding** — a numeric fingerprint of the meaning.

This one field carries three separate jobs downstream:

| Used by | For |
| --- | --- |
| [Group](05-group.md) | finding articles about the same event |
| [Match](07-match.md) | matching a topic's *meaning*, catching paraphrases keywords miss |
| [Judge](06-judge.md) | retrieving the last 30 days of coverage on the subject |

It is stored on both `articles` and `stories`, in Postgres via `pgvector`
([Data model](11-data-model.md)). Embedding cost scales with articles/day, is batched, and
is a minor line item ([Cost](13-cost.md)).

**Changing the embedding model is a corpus-wide migration**, because grouping decisions,
match scores and novelty windows were all computed in the old space. Treat the choice as
semi-permanent, or plan for a backfill.

---

## Storage split

```
Postgres  →  url, title, published_at, image, language, site_id, embedding, story_id
S3        →  article text, raw HTML
```

Postgres stores a **key** (`text_key`), never the body. Keeping bodies out of the database
keeps the working set small enough that the tables that are read constantly stay fast, and
keeps raw HTML available for re-extraction when the parser improves.

---

## Failure modes

| Symptom | Likely cause | Mitigation |
| --- | --- | --- |
| Empty or truncated body | Site is JS-rendered, or hard paywall | Accept metadata-only; the article still works |
| Wrong publication date | Site emits modified-date as `datePublished` | Prefer JSON-LD `datePublished`, sanity-check against first-seen time |
| Wrong language tag | Missing `inLanguage` | Detect from body; matters for GDELT-sourced non-English content |
| Boilerplate in the body | Extraction fell through to a bad heuristic | Bad bodies poison embeddings — score extraction confidence and drop low-confidence text rather than embedding noise |
