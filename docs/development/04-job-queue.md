# 4 — Job queue & scheduler

← [Database](03-database.md) · [Dev README](README.md) · next → [Worker stages](05-worker-stages.md)

Two mechanisms, both columns in Postgres, both replacing a service we don't run
([runtime](../architecture/12-runtime.md)).

---

## The claim loop

```python
# techtrend/platform/queue.py
from __future__ import annotations
import asyncio, socket, os
from dataclasses import dataclass
from sqlalchemy import text
from techtrend.platform.db import session_scope

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

CLAIM = text("""
    WITH claimed AS (
        SELECT id FROM jobs
         WHERE state = 'pending'
           AND stage = ANY(:stages)
           AND run_after <= now()
         ORDER BY priority, run_after
         LIMIT :batch
         FOR UPDATE SKIP LOCKED          -- ← the whole trick
    )
    UPDATE jobs j
       SET state = 'running',
           locked_by = :worker,
           locked_at = now(),
           attempts = j.attempts + 1
      FROM claimed c
     WHERE j.id = c.id
    RETURNING j.id, j.stage, j.key, j.payload, j.attempts, j.max_attempts;
""")

@dataclass(frozen=True)
class Job:
    id: int
    stage: str
    key: str
    payload: dict
    attempts: int
    max_attempts: int

async def claim(stages: list[str], batch: int = 8) -> list[Job]:
    async with session_scope() as s:
        rows = await s.execute(
            CLAIM, {"stages": stages, "batch": batch, "worker": WORKER_ID}
        )
        return [Job(*r) for r in rows]
```

`FOR UPDATE SKIP LOCKED` is what lets N workers poll the same table without contending:
each transaction locks rows nobody else holds and skips the rest. No coordinator, no
partition assignment, no rebalancing on scale-up.

### Completion and failure

```python
async def complete(job_id: int) -> None:
    async with session_scope() as s:
        await s.execute(
            text("UPDATE jobs SET state='done', locked_by=NULL WHERE id=:id"),
            {"id": job_id},
        )

async def fail(job: Job, err: str) -> None:
    """Exponential backoff with a cap; dead-letter after max_attempts."""
    terminal = job.attempts >= job.max_attempts
    async with session_scope() as s:
        await s.execute(text("""
            UPDATE jobs
               SET state      = CASE WHEN :terminal THEN 'failed' ELSE 'pending' END,
                   run_after  = now() + make_interval(secs => LEAST(3600, 2 ^ :attempts * 10)),
                   locked_by  = NULL,
                   last_error = :err
             WHERE id = :id
        """), {"id": job.id, "attempts": job.attempts, "terminal": terminal, "err": err[:2000]})
```

### Enqueue is idempotent

```python
async def enqueue(stage: str, key: str, payload: dict, *,
                  priority: int = 100, session=None) -> None:
    """Uses the caller's session when given — so the job commits with the write
    that caused it. That atomicity is the main reason not to use a broker."""
    stmt = text("""
        INSERT INTO jobs (stage, key, payload, priority)
        VALUES (:stage, :key, :payload, :priority)
        ON CONFLICT (stage, key) DO NOTHING
    """)
    if session is not None:
        await session.execute(stmt, {...})
    else:
        async with session_scope() as s:
            await s.execute(stmt, {...})
```

> **The atomicity point is the argument.** With a broker, "row committed but message lost"
> and "message sent but row rolled back" are both real states you must design around. Here
> the job row and the article row are in the same transaction: either both exist or neither
> does.

---

## The worker loop

```python
# techtrend/cli.py (worker command, condensed)
async def run_worker(stages: list[str], concurrency: int = 8) -> None:
    sem = asyncio.Semaphore(concurrency)
    handlers = load_handlers(stages)          # stage name -> async def run(job, deps)
    stop = install_signal_handlers()          # SIGTERM -> graceful drain

    while not stop.is_set():
        jobs = await claim(stages, batch=concurrency)
        if not jobs:
            await asyncio.sleep(POLL_IDLE_S)  # 0.5s; jittered to avoid thundering herd
            continue
        await asyncio.gather(*(_run_one(j, handlers, sem) for j in jobs))

async def _run_one(job, handlers, sem):
    async with sem:
        with telemetry.span("job", stage=job.stage, key=job.key):
            try:
                await handlers[job.stage](job, DEPS)
                await complete(job.id)
            except RetryableError as e:
                await fail(job, str(e))
            except Exception as e:
                telemetry.exception(e, job=job.key)
                await fail(job, repr(e))
```

**Graceful shutdown**: SIGTERM stops claiming; in-flight jobs finish; the process exits.
A job killed mid-flight is reclaimed by the reaper below — which is safe precisely because
every stage is idempotent ([worker stages](05-worker-stages.md)).

### The reaper

```sql
-- Runs every minute in the maintenance stage. A crashed worker's jobs
-- become claimable again after the lease expires.
UPDATE jobs
   SET state = 'pending', locked_by = NULL
 WHERE state = 'running'
   AND locked_at < now() - interval '15 minutes';
```

---

## The scheduler is a column

There is no scheduler process. [Collect](../architecture/03-collect.md)'s ~20,000 endpoints
across three tiers, plus adaptive back-off, are one indexed timestamp:

```python
# techtrend/shared/collect/schedule.py
TIER_BASE_S = {"A": 120, "B": 600, "C": 2700}

def next_interval(tier: str, published_something: bool, quiet_streak: int) -> int:
    """A site that publishes on every check gets checked more often; a site
    quiet three times in a row gets backed off."""
    base = TIER_BASE_S[tier]
    if published_something:
        return max(base // 4, 60)
    if quiet_streak >= 3:
        return min(base * 4, 6 * 3600)
    return base
```

Claiming due endpoints uses the same `SKIP LOCKED` shape:

```sql
WITH due AS (
    SELECT id FROM endpoints
     WHERE next_check_at <= now() AND failure_streak < 10
     ORDER BY next_check_at
     LIMIT 64
     FOR UPDATE SKIP LOCKED
)
UPDATE endpoints e
   SET next_check_at = now() + interval '5 minutes'   -- lease; real value set after the fetch
  FROM due d WHERE e.id = d.id
RETURNING e.*;
```

The provisional five-minute bump is a lease: if the worker dies mid-fetch, the endpoint
becomes due again shortly rather than never.

**What this buys** ([runtime](../architecture/12-runtime.md)): no singleton to make highly
available, no leader election, and adding a worker adds schedule throughput. The classic
"cron container died and nobody noticed for a week" failure mode does not exist because
there is no cron container.

---

## Priority

`priority` is a small int, lower first:

| Priority | Used for |
| --- | --- |
| 10 | Tier A breaking — judge immediately, interactive AI path |
| 50 | Tier A/B routine |
| 100 | Default |
| 200 | Backfill, re-extraction after a parser fix |

The judge stage reads priority to decide interactive vs. batch
([AI layer](06-ai-layer.md)): priority ≤ 50 goes to the live API, the rest goes into the
Batch API at half price.

---

## Operating it with SQL

This is the payoff of not having a broker — every operational question is a query:

```sql
-- Backlog by stage: the primary health check
SELECT stage, state, count(*), min(run_after)
  FROM jobs GROUP BY 1, 2 ORDER BY 1, 2;

-- What's stuck, and why
SELECT stage, key, attempts, last_error
  FROM jobs WHERE state = 'failed' ORDER BY id DESC LIMIT 50;

-- Are we keeping up with the schedule?
SELECT count(*) FROM endpoints WHERE next_check_at < now() - interval '5 minutes';

-- Retry a dead-lettered batch after fixing the bug
UPDATE jobs SET state='pending', attempts=0, run_after=now()
 WHERE state='failed' AND stage='read' AND last_error LIKE '%TimeoutError%';
```

The last one is worth noting: **replaying a dead letter is an `UPDATE`.** No broker
tooling, no message re-publishing, no separate DLQ topic to drain.

---

## Failure modes

| Symptom | Cause | Response |
| --- | --- | --- |
| Backlog grows on one stage | That stage is slower than upstream | Add workers for that stage only (`--stage judge`) |
| `jobs` table bloats | Done-job cleanup not running | Check the maintenance stage; vacuum |
| Claim query slows | `jobs_claimable_idx` bloated by churn | Partial index on `state='pending'` keeps it small; reindex if needed |
| Same job retried forever | Non-idempotent stage, or a poison payload | `max_attempts` dead-letters it; the row holds `last_error` |
| Endpoints all due at once | Mass `next_check_at` reset after a deploy | Jitter the initial value; the lease bump prevents a stampede |
