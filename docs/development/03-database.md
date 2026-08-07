# 3 — Database

← [Tech stack](02-tech-stack.md) · [Dev README](README.md) · next → [Job queue & scheduler](04-job-queue.md)

Full DDL for [the data model](../architecture/11-data-model.md). Grouped by layer, because
layer determines who may write.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;
```

---

## Shared layer

```sql
CREATE TYPE site_tier   AS ENUM ('A', 'B', 'C');
CREATE TYPE endpoint_kind AS ENUM ('feed', 'sitemap');
CREATE TYPE story_type  AS ENUM (
    'original_reporting', 'official_announcement', 'analysis',
    'rewrite', 'roundup', 'routine_data', 'speculation'
);

CREATE TABLE sites (
    id           bigserial PRIMARY KEY,
    domain       text        NOT NULL UNIQUE,
    name         text        NOT NULL,
    tier         site_tier   NOT NULL DEFAULT 'C',
    country      char(2),
    language     text,
    authority    real        NOT NULL DEFAULT 0.5,   -- 0..1, feeds importance + novelty guard
    paywall      boolean     NOT NULL DEFAULT false,
    robots_txt   text,
    robots_at    timestamptz,
    opt_out_at   timestamptz,                        -- publisher removal request; gates collection
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE endpoints (
    id             bigserial PRIMARY KEY,
    site_id        bigint      NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    url            text        NOT NULL,
    kind           endpoint_kind NOT NULL,
    etag           text,
    last_modified  text,
    next_check_at  timestamptz NOT NULL DEFAULT now(),  -- this column IS the scheduler
    interval_s     integer     NOT NULL DEFAULT 600,
    quiet_streak   smallint    NOT NULL DEFAULT 0,      -- drives adaptive backoff
    last_status    smallint,
    failure_streak smallint    NOT NULL DEFAULT 0,
    UNIQUE (site_id, url)
);

-- The scheduler's only hot query. Partial index keeps it small: rows far in the
-- future are excluded, so the index stays roughly the size of the due backlog.
CREATE INDEX endpoints_due_idx ON endpoints (next_check_at)
    WHERE failure_streak < 10;

CREATE TABLE articles (
    id             bigserial PRIMARY KEY,
    url            text        NOT NULL,
    url_hash       bytea       NOT NULL UNIQUE,   -- sha256 of the canonical URL
    site_id        bigint      NOT NULL REFERENCES sites(id),
    title          text        NOT NULL,
    text_key       text,                          -- S3 key. NEVER the body itself.
    html_key       text,
    published_at   timestamptz NOT NULL,
    author         text,
    image_url      text,
    language       text        NOT NULL DEFAULT 'en',
    extraction     jsonb       NOT NULL DEFAULT '{}',  -- {source: jsonld|trafilatura, confidence: 0.9}
    embedding      vector(1024),
    story_id       bigint      REFERENCES stories(id) ON DELETE SET NULL,
    fetched_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX articles_recent_idx    ON articles (published_at DESC);
CREATE INDEX articles_story_idx     ON articles (story_id) WHERE story_id IS NOT NULL;
CREATE INDEX articles_site_day_idx  ON articles (site_id, published_at DESC);  -- coverage audit
CREATE INDEX articles_ungrouped_idx ON articles (published_at) WHERE story_id IS NULL;

-- Grouping only ever searches the last 72h, so the ANN index covers a small
-- slice; novelty's 30-day lookup uses the same index with a wider filter.
CREATE INDEX articles_embedding_idx ON articles
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE TABLE stories (
    id                  bigserial PRIMARY KEY,
    display_article_id  bigint      REFERENCES articles(id),
    source_count        integer     NOT NULL DEFAULT 1,
    subject_key         text,                        -- coarse subject bucket for the 30d novelty window
    summary             text,
    story_type          story_type,
    novelty_score       real,                        -- 0..1, fraction of facts not seen in 30d
    hedge_score         real,                        -- 0..1, hedged / (hedged + factual)
    importance          real,                        -- precomputed, identical for every user
    facts               jsonb NOT NULL DEFAULT '[]', -- extracted entities/numbers/dates/quotes
    embedding           vector(1024),
    judged_at           timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX stories_unjudged_idx ON stories (created_at) WHERE judged_at IS NULL;
CREATE INDEX stories_recent_idx   ON stories (created_at DESC);
CREATE INDEX stories_subject_idx  ON stories (subject_key, created_at DESC);
CREATE INDEX stories_embedding_idx ON stories
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

**`stories.facts` is what makes novelty computable.** It holds the extracted entities,
numbers, dates and quotes; the 30-day comparison in [judge](../architecture/06-judge.md) is
a set operation against the `facts` of prior stories sharing a `subject_key`, not a second
model call.

**No shared table has a `user_id`.** That is invariant #11, checkable by inspection —
`grep -l user_id migrations/` must never match a shared-layer table.

---

## Topic layer

```sql
CREATE TABLE topics (
    id               bigserial PRIMARY KEY,
    fingerprint      bytea       NOT NULL UNIQUE,  -- ← the deduplication mechanism
    title            text        NOT NULL,
    must             text[]      NOT NULL DEFAULT '{}',
    should           text[]      NOT NULL DEFAULT '{}',
    exclude          text[]      NOT NULL DEFAULT '{}',   -- SHARED across subscribers
    entities         text[]      NOT NULL DEFAULT '{}',
    embedding        vector(1024) NOT NULL,
    floor            real        NOT NULL DEFAULT 0.35,
    subscriber_count integer     NOT NULL DEFAULT 0,
    match_rate       real,                                -- stories/day, powers "about 6 a day"
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX topics_embedding_idx ON topics
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- The reverse index: a search engine run backwards.
CREATE TABLE topic_terms (
    term     text   NOT NULL,
    topic_id bigint NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    PRIMARY KEY (term, topic_id)
);
CREATE INDEX topic_terms_term_idx ON topic_terms (term);

CREATE TABLE matches (
    topic_id    bigint      NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    story_id    bigint      NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    match_score real        NOT NULL,
    matched_by  text[]      NOT NULL DEFAULT '{}',  -- which keywords hit → keyword-level feedback
    matched_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (topic_id, story_id)
) PARTITION BY RANGE (matched_at);

CREATE INDEX matches_topic_recent_idx ON matches (topic_id, matched_at DESC);

-- Proposed topic changes. NEVER applied without the user accepting.
CREATE TYPE suggestion_kind AS ENUM ('add_term', 'add_exclude', 'broaden', 'narrow');
CREATE TABLE suggestions (
    id          bigserial PRIMARY KEY,
    user_id     bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_id    bigint NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    kind        suggestion_kind NOT NULL,
    payload     jsonb NOT NULL,
    evidence    text,                     -- "appeared in 12 stories you opened"
    state       text NOT NULL DEFAULT 'pending',  -- pending|accepted|dismissed
    created_at  timestamptz NOT NULL DEFAULT now()
);
```

**`matches` is partitioned by month and dropped at 30 days** — it is the only table that
would otherwise grow with stories × topics, and
[the data model](../architecture/11-data-model.md) explicitly treats it as recomputable
cache. Dropping a partition is instant; a `DELETE` at this volume would not be.

**`matched_by` is the column that makes keyword-level feedback possible** — the card can
say *"matched: price target"* and the user can act on the keyword rather than the article
([feedback](../architecture/09-feedback.md)).

**`suggestions` exists so `topics` never gets written by a learning process.** That is
invariant #12 expressed as a separate table rather than a discipline.

---

## Personal layer

```sql
CREATE TABLE users (
    id            bigserial PRIMARY KEY,
    email         citext      NOT NULL UNIQUE,
    timezone      text        NOT NULL DEFAULT 'UTC',
    digest_hour   smallint    NOT NULL DEFAULT 8,
    push_settings jsonb       NOT NULL DEFAULT '{"breaking": true, "max_per_day": 2}',
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE subscriptions (
    user_id          bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_id         bigint NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    label            text,                        -- user's own name for it
    personal_excludes text[] NOT NULL DEFAULT '{}',  -- ← "just for me", never touches topics.exclude
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, topic_id)
);

CREATE TYPE weight_kind AS ENUM ('type', 'source', 'keyword');
CREATE TABLE weights (
    user_id bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind    weight_kind NOT NULL,
    key     text        NOT NULL,
    value   real        NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, kind, key)
);

CREATE TYPE seen_state AS ENUM ('shown', 'opened', 'tapped', 'skipped', 'hidden');
CREATE TABLE seen (
    user_id  bigint     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    story_id bigint     NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    state    seen_state NOT NULL,
    position smallint,                    -- for position-bias correction
    at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, story_id)
);

-- Note the absence of a 'click' member. Invariant #8, enforced by the type.
CREATE TYPE event_kind AS ENUM (
    'shown', 'expanded', 'dwell', 'tapped_through', 'saved', 'shared',
    'scrolled_past', 'skipped', 'hidden', 'best_of_day'
);
CREATE TABLE events (
    id       bigserial   PRIMARY KEY,
    user_id  bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    story_id bigint      REFERENCES stories(id) ON DELETE SET NULL,
    kind     event_kind  NOT NULL,
    reason   text,                        -- dismissal reason: the most valuable, rarest signal
    meta     jsonb       NOT NULL DEFAULT '{}',
    at       timestamptz NOT NULL DEFAULT now()
) PARTITION BY RANGE (at);

CREATE INDEX events_user_recent_idx ON events (user_id, at DESC);
```

**`event_kind` has no `click`.** [Invariant #8](../architecture/14-invariants.md) says rank
on tap-through and dwell, never raw clicks — so the enum omits the concept. There is no
column to accidentally start ranking on.

**`subscriptions.personal_excludes` vs `topics.exclude`** is the most likely place to break
invariants #11 and #12 in practice. The former is one user; the latter is every subscriber.
Code review rule: any write to `topics.exclude` must originate from an explicit user edit
of *their own* topic, never from `personal/`.

---

## Jobs table

```sql
CREATE TYPE job_state AS ENUM ('pending', 'running', 'done', 'failed');

CREATE TABLE jobs (
    id           bigserial   PRIMARY KEY,
    stage        text        NOT NULL,        -- collect|read|group|judge|match
    key          text        NOT NULL,        -- idempotency key, e.g. "read:article:12345"
    payload      jsonb       NOT NULL DEFAULT '{}',
    state        job_state   NOT NULL DEFAULT 'pending',
    priority     smallint    NOT NULL DEFAULT 100,   -- lower runs first; Tier A breaking = 10
    run_after    timestamptz NOT NULL DEFAULT now(),
    attempts     smallint    NOT NULL DEFAULT 0,
    max_attempts smallint    NOT NULL DEFAULT 5,
    locked_by    text,
    locked_at    timestamptz,
    last_error   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (stage, key)              -- ← enqueue is idempotent by construction
);

-- The claim query's index. Partial: finished jobs leave it immediately.
CREATE INDEX jobs_claimable_idx ON jobs (stage, priority, run_after)
    WHERE state = 'pending';

CREATE INDEX jobs_stuck_idx ON jobs (locked_at) WHERE state = 'running';
```

The `UNIQUE (stage, key)` constraint is what makes "enqueue twice" a no-op rather than
double work: producers use `INSERT ... ON CONFLICT (stage, key) DO NOTHING`.

---

## Retention

| Table | Kept | Mechanism |
| --- | --- | --- |
| `matches` | 30 days | Drop monthly partition — recomputable |
| `events` | 400 days | Drop partition; aggregate into `weights` before dropping |
| `jobs` (done) | 7 days | Nightly `DELETE WHERE state='done'` |
| `articles` | indefinite | Novelty needs 30d; the corpus is the asset |
| S3 `html_key` | 90 days | Lifecycle rule — keeps re-extraction possible after a parser fix |
| S3 `text_key` | indefinite | Cheap, and required to re-judge |

---

## Backup priority

Follows what is **recoverable**, not table size
([data model](../architecture/11-data-model.md)):

1. **`events`, `weights`, `seen`, `users`, `subscriptions`** — irreplaceable. It is the
   user's own history and cannot be regenerated at any price.
2. **`stories`** (summaries, novelty) — regenerable, at real AI cost.
3. **`articles` + S3** — partly recoverable; feeds only expose recent items.
4. **`matches`, `topic_terms`** — fully derived. Do not back up.

---

## Operational notes

- **Connection pooling**: PgBouncer in transaction mode. Workers hold connections for the
  duration of a job; the API does not. Size the API pool small and the worker pool by
  concurrency.
- **`SKIP LOCKED` and PgBouncer**: the claim query uses an explicit transaction; transaction
  pooling is compatible, session pooling is not needed.
- **Vector index maintenance**: HNSW build is expensive. Create indexes `CONCURRENTLY` and
  never rebuild during a backfill — load first, index after
  ([milestones](17-milestones.md) step 1).
- **The single point of contention is Postgres** ([runtime](../architecture/12-runtime.md)).
  Its saturation metrics lead the dashboard in [observability](13-observability.md).
