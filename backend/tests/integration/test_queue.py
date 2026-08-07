"""The queue is the load-bearing piece of not running a broker. Prove it works."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from techtrend.platform.db import session_scope
from techtrend.platform.queue import Job, claim, complete, enqueue, fail, reap_stale


async def test_job_round_trip() -> None:
    """M0 exit criterion: a job round-trips through the queue."""
    await enqueue("read", "read:article:abc", {"url": "https://example.com/x"})

    jobs = await claim(["read"])
    assert len(jobs) == 1
    assert jobs[0].key == "read:article:abc"
    assert jobs[0].payload["url"] == "https://example.com/x"
    assert jobs[0].attempts == 1

    await complete(jobs[0].id)
    async with session_scope() as s:
        state = await s.scalar(text("SELECT state FROM jobs WHERE key='read:article:abc'"))
    assert state == "done"
    assert await claim(["read"]) == []


async def test_enqueue_is_idempotent() -> None:
    """UNIQUE (stage, key) + ON CONFLICT DO NOTHING: enqueue twice is a no-op."""
    for _ in range(5):
        await enqueue("read", "read:article:same", {"n": 1})
    async with session_scope() as s:
        n = await s.scalar(text("SELECT count(*) FROM jobs WHERE key='read:article:same'"))
    assert n == 1


async def test_enqueue_joins_the_callers_transaction() -> None:
    """The job row and the row that caused it either both exist or neither does.

    This atomicity is the main argument against a broker.
    """
    try:
        async with session_scope() as s:
            await enqueue("read", "read:article:rollback", {}, session=s)
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    async with session_scope() as s:
        n = await s.scalar(text("SELECT count(*) FROM jobs WHERE key='read:article:rollback'"))
    assert n == 0, "job survived a rolled-back transaction"


async def test_skip_locked_never_double_claims() -> None:
    """Ten concurrent workers, a hundred jobs, zero collisions."""
    for i in range(100):
        await enqueue("read", f"read:article:{i}", {"i": i})

    batches = await asyncio.gather(*(claim(["read"], batch=10) for _ in range(10)))
    ids = [j.id for b in batches for j in b]

    assert len(ids) == 100, f"expected 100 claims, got {len(ids)}"
    assert len(set(ids)) == 100, "a job was claimed by two workers"


async def test_priority_orders_the_queue() -> None:
    await enqueue("judge", "judge:story:low", {}, priority=100)
    await enqueue("judge", "judge:story:breaking", {}, priority=10)
    jobs = await claim(["judge"], batch=1)
    assert jobs[0].key == "judge:story:breaking"


async def test_failure_backs_off_then_dead_letters() -> None:
    await enqueue("read", "read:article:bad", {})
    job = (await claim(["read"]))[0]

    await fail(job, "TimeoutError")
    async with session_scope() as s:
        row = (
            await s.execute(
                text("SELECT state, last_error, run_after > now() FROM jobs WHERE id=:i"),
                {"i": job.id},
            )
        ).one()
    assert row[0] == "pending"  # returned for retry
    assert "TimeoutError" in row[1]
    assert row[2] is True  # with backoff

    exhausted = Job(job.id, job.stage, job.key, job.payload, 5, 5)
    await fail(exhausted, "still broken")
    async with session_scope() as s:
        state = await s.scalar(text("SELECT state FROM jobs WHERE id=:i"), {"i": job.id})
    assert state == "failed"  # dead-lettered, error kept on the row


async def test_reaper_reclaims_a_crashed_workers_job() -> None:
    """Safe only because every stage is idempotent."""
    await enqueue("read", "read:article:crashed", {})
    job = (await claim(["read"]))[0]
    assert await claim(["read"]) == []  # locked

    async with session_scope() as s:
        await s.execute(
            text("UPDATE jobs SET locked_at = now() - interval '1 hour' WHERE id=:i"),
            {"i": job.id},
        )

    assert await reap_stale() == 1
    reclaimed = await claim(["read"])
    assert len(reclaimed) == 1
    assert reclaimed[0].key == "read:article:crashed"
