"""The job queue and the scheduler -- both are columns in Postgres.

No message broker: jobs live in a table, claimed with SELECT ... FOR UPDATE
SKIP LOCKED. Enqueue can join the caller's transaction, so a job row and the
row that caused it either both exist or neither does.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from techtrend.platform.config import settings
from techtrend.platform.db import session_scope

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


class RetryableError(Exception):
    """Transient. The job returns to `pending` with exponential backoff."""


class FatalError(Exception):
    """Permanent. The job is dead-lettered immediately."""


@dataclass(frozen=True)
class Job:
    id: int
    stage: str
    key: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


_CLAIM = text("""
    WITH claimed AS (
        SELECT id FROM jobs
         WHERE state = 'pending'
           AND stage = ANY(:stages)
           AND run_after <= now()
         ORDER BY priority, run_after
         LIMIT :batch
         FOR UPDATE SKIP LOCKED
    )
    UPDATE jobs j
       SET state = 'running',
           locked_by = :worker,
           locked_at = now(),
           attempts = j.attempts + 1
      FROM claimed c
     WHERE j.id = c.id
    RETURNING j.id, j.stage, j.key, j.payload, j.attempts, j.max_attempts
""")

_ENQUEUE = text("""
    INSERT INTO jobs (stage, key, payload, priority, run_after)
    VALUES (:stage, :key, CAST(:payload AS jsonb), :priority,
            now() + make_interval(secs => :delay_s))
    ON CONFLICT (stage, key) DO NOTHING
""")

_COMPLETE = text("""
    UPDATE jobs SET state = 'done', locked_by = NULL, locked_at = NULL
     WHERE id = :id
""")

_FAIL = text("""
    UPDATE jobs
       SET state      = CASE WHEN :terminal THEN 'failed' ELSE 'pending' END,
           run_after  = now() + make_interval(secs => LEAST(3600, POWER(2, :attempts) * 10)),
           locked_by  = NULL,
           locked_at  = NULL,
           last_error = :err
     WHERE id = :id
""")

_REAP = text("""
    UPDATE jobs
       SET state = 'pending', locked_by = NULL, locked_at = NULL
     WHERE state = 'running'
       AND locked_at < now() - make_interval(mins => :lease)
""")


async def claim(stages: list[str], batch: int = 8) -> list[Job]:
    """Claim up to `batch` due jobs. Concurrent workers never collide."""
    async with session_scope() as s:
        rows = await s.execute(_CLAIM, {"stages": stages, "batch": batch, "worker": WORKER_ID})
        return [
            Job(id=r[0], stage=r[1], key=r[2], payload=r[3] or {}, attempts=r[4], max_attempts=r[5])
            for r in rows
        ]


async def enqueue(
    stage: str,
    key: str,
    payload: dict[str, Any] | None = None,
    *,
    priority: int = 100,
    delay_s: float = 0.0,
    session: AsyncSession | None = None,
) -> bool:
    """Idempotent by construction: UNIQUE (stage, key) + ON CONFLICT DO NOTHING.

    Pass `session` to commit the job with the write that caused it.
    Returns True if a new job row was inserted, False if it already existed.
    """
    import json

    params = {
        "stage": stage,
        "key": key,
        "payload": json.dumps(payload or {}),
        "priority": priority,
        "delay_s": delay_s,
    }
    if session is not None:
        result = await session.execute(_ENQUEUE, params)
    else:
        async with session_scope() as s:
            result = await s.execute(_ENQUEUE, params)
    return bool(cast("CursorResult[Any]", result).rowcount or 0)


async def complete(job_id: int) -> None:
    async with session_scope() as s:
        await s.execute(_COMPLETE, {"id": job_id})


async def fail(job: Job, err: str) -> None:
    terminal = job.attempts >= job.max_attempts
    async with session_scope() as s:
        await s.execute(
            _FAIL,
            {
                "id": job.id,
                "attempts": min(job.attempts, 8),
                "terminal": terminal,
                "err": err[:2000],
            },
        )


async def reap_stale() -> int:
    """A crashed worker's jobs become claimable again after the lease expires.

    Safe only because every stage is idempotent.
    """
    async with session_scope() as s:
        result = await s.execute(_REAP, {"lease": settings().job_lease_minutes})
        return int(cast("CursorResult[Any]", result).rowcount or 0)


_PURGE = text("""
    DELETE FROM jobs WHERE state = 'done' AND created_at < now() - interval '1 day'
""")


async def purge_done() -> int:
    """Done rows have served their idempotency window; the durable dedup is the
    domain unique key (e.g. articles.url_hash), not the jobs table."""
    async with session_scope() as s:
        result = await s.execute(_PURGE)
        return int(cast("CursorResult[Any]", result).rowcount or 0)


async def backlog() -> list[tuple[str, str, int]]:
    """(stage, state, count) -- the primary operational health check."""
    async with session_scope() as s:
        rows = await s.execute(
            text("SELECT stage, state::text, count(*) FROM jobs GROUP BY 1, 2 ORDER BY 1, 2")
        )
        return [(r[0], r[1], r[2]) for r in rows]
