"""`techtrend api` and `techtrend worker`.

One image, two commands. Same code, same dependencies, same config -- the stage
list is a flag. There is no scheduler process and no consumer service.
"""

from __future__ import annotations

import asyncio
import signal
from typing import Annotated

import typer

from techtrend import __version__
from techtrend.platform import queue, telemetry
from techtrend.platform.config import check_production_invariants, settings

app = typer.Typer(add_completion=False, help="TechTrend")


def bootstrap() -> None:
    s = settings()
    telemetry.init(s.env, s.log_level)
    check_production_invariants(s)


@app.command()
def api(
    host: str = "0.0.0.0",  # noqa: S104 - containers bind all interfaces
    port: int = 8000,
    workers: int = 1,
    reload: bool = False,
) -> None:
    """Run the read path: reads, ranks, returns."""
    bootstrap()
    import uvicorn

    uvicorn.run(
        "techtrend.api.app:app",
        host=host,
        port=port,
        workers=workers if not reload else 1,
        reload=reload,
        log_config=None,
    )


@app.command()
def worker(
    stage: Annotated[str, typer.Option(help="comma-separated stages")] = "maintenance",
    concurrency: int = 0,
) -> None:
    """Run the write path. Scale by adding copies."""
    bootstrap()
    stages = [s.strip() for s in stage.split(",") if s.strip()]
    asyncio.run(_run_worker(stages, concurrency or settings().worker_concurrency))


@app.command()
def backlog() -> None:
    """Jobs by stage and state -- the primary health check."""
    bootstrap()

    async def _go() -> None:
        for st, state, n in await queue.backlog():
            typer.echo(f"{st:<14} {state:<10} {n}")

    asyncio.run(_go())


@app.command()
def enqueue(stage: str, key: str, priority: int = 100) -> None:
    """Put one job on the queue (useful for smoke tests)."""
    bootstrap()
    asyncio.run(queue.enqueue(stage, key, {}, priority=priority))
    typer.echo(f"enqueued {stage}:{key}")


@app.command("seed-demo")
def seed_demo_cmd(
    email: str = "demo@example.com",
    password: str = "hunter2hunter2",  # noqa: S107 - local demo account
) -> None:
    """Seed a user, a topic and five judged stories so the dashboard is non-empty."""
    bootstrap()
    from techtrend.api.deps import hash_password
    from techtrend.platform.seed import seed_demo

    out = asyncio.run(seed_demo(email, hash_password(password)))
    typer.echo(f"user={out['user_id']} topic={out['topic_id']} stories={out['stories']}")
    typer.echo(f"login: {email} / {password}")


@app.command("seed-sites")
def seed_sites_cmd() -> None:
    """Load the curated tech source list into sites/endpoints (idempotent)."""
    bootstrap()
    from techtrend.shared.collect.seed import seed_sites

    out = asyncio.run(seed_sites())
    typer.echo(f"sites={out['sites']} endpoints={out['endpoints']}")


@app.command("print-top-stories")
def print_top_stories_cmd(limit: int = 15) -> None:
    """The day's top stories by importance -- the M2 acceptance test is
    reading these three mornings running and finding them worth it."""
    bootstrap()
    from sqlalchemy import text as sql

    from techtrend.platform.db import session_scope

    async def _go() -> None:
        async with session_scope() as s:
            rows = await s.execute(
                sql("""
                    SELECT st.importance, st.novelty_score, st.story_type,
                           st.source_count, a.title, st.summary
                      FROM stories st JOIN articles a ON a.id = st.display_article_id
                     WHERE st.judged_at IS NOT NULL
                       AND st.created_at > now() - interval '48 hours'
                     ORDER BY st.importance DESC NULLS LAST
                     LIMIT :n
                """),
                {"n": limit},
            )
            for r in rows:
                nov = f"{r.novelty_score:.2f}" if r.novelty_score is not None else "--"
                typer.echo(
                    f"[{r.importance:.2f}] nov={nov} {r.story_type or 'unjudged':<22}"
                    f" {r.source_count:>2}src  {r.title[:70]}"
                )
                if r.summary:
                    typer.echo(f"       {r.summary[:150]}")

    asyncio.run(_go())


@app.command("backfill-embeddings")
def backfill_embeddings_cmd(batch: int = 64) -> None:
    """Embed + entity-extract articles that predate the embedding column."""
    bootstrap()
    from techtrend.shared.read.backfill import backfill_embeddings

    n = asyncio.run(backfill_embeddings(batch))
    typer.echo(f"embedded {n} articles")


@app.command()
def version() -> None:
    typer.echo(__version__)


# --------------------------------------------------------------- worker loop

Handler = "Callable[[queue.Job], Awaitable[None]]"


async def _noop(job: queue.Job) -> None:
    """M0 placeholder. Real stages land in M1+ (collect, read, group, judge, match)."""
    telemetry.log.info("job.noop", stage=job.stage, key=job.key)


async def _collect(job: queue.Job) -> None:
    from techtrend.shared.collect import worker as collect_worker

    await collect_worker.run(job)


async def _read(job: queue.Job) -> None:
    from techtrend.shared.read import worker as read_worker

    await read_worker.run(job)


async def _group(job: queue.Job) -> None:
    from techtrend.shared.group import worker as group_worker

    await group_worker.run(job)


async def _judge(job: queue.Job) -> None:
    from techtrend.shared.judge import worker as judge_worker

    await judge_worker.run(job)


async def _maintenance(job: queue.Job) -> None:
    reclaimed = await queue.reap_stale()
    if reclaimed:
        telemetry.log.info("jobs.reaped", count=reclaimed)
    purged = await queue.purge_done()
    if purged:
        telemetry.log.info("jobs.purged", count=purged)


HANDLERS = {
    "collect": _collect,
    "read": _read,
    "group": _group,
    "judge": _judge,
    "match": _noop,
    "feedback": _noop,
    "maintenance": _maintenance,
}


async def _run_worker(stages: list[str], concurrency: int) -> None:
    unknown = set(stages) - HANDLERS.keys()
    if unknown:
        raise typer.BadParameter(f"unknown stage(s): {', '.join(sorted(unknown))}")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    sem = asyncio.Semaphore(concurrency)
    telemetry.log.info("worker.start", stages=stages, concurrency=concurrency)

    sweep = None
    if "collect" in stages:
        from techtrend.shared.collect import worker as collect_worker

        sweep = collect_worker.sweep_due

    while not stop.is_set():
        if sweep is not None:
            # The scheduler is the `next_check_at` column; this is its only reader.
            await sweep()
        jobs = await queue.claim(stages, batch=concurrency)
        if not jobs:
            # Graceful shutdown: stop claiming, let in-flight jobs finish.
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings().worker_poll_idle_s)
            except TimeoutError:
                pass
            continue
        await asyncio.gather(*(_run_one(j, sem) for j in jobs))

    telemetry.log.info("worker.stop")


async def _run_one(job: queue.Job, sem: asyncio.Semaphore) -> None:
    async with sem:
        with telemetry.span("job", stage=job.stage, key=job.key):
            try:
                with telemetry.JOB_TIME.labels(stage=job.stage).time():
                    await HANDLERS[job.stage](job)
                await queue.complete(job.id)
                telemetry.JOBS.labels(stage=job.stage, outcome="done").inc()
            except queue.FatalError as e:
                await queue.fail(
                    queue.Job(
                        job.id, job.stage, job.key, job.payload, job.max_attempts, job.max_attempts
                    ),
                    str(e),
                )
                telemetry.JOBS.labels(stage=job.stage, outcome="fatal").inc()
            except Exception as e:  # noqa: BLE001 - the loop must survive any handler
                telemetry.log.exception("job.failed", stage=job.stage, key=job.key)
                await queue.fail(job, repr(e))
                telemetry.JOBS.labels(stage=job.stage, outcome="retry").inc()


if __name__ == "__main__":
    app()
