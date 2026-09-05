"""`techtrend api` and `techtrend worker`.

One image, two commands. Same code, same dependencies, same config -- the stage
list is a flag. There is no scheduler process and no consumer service.
"""

from __future__ import annotations

import asyncio
import signal
import time
from typing import Annotated

import typer

from techtrend import __version__
from techtrend.platform import queue, telemetry
from techtrend.platform.config import check_production_invariants, settings
from techtrend.platform.types import PRIORITY_BACKFILL

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
def slackbot() -> None:
    """Answer @mentions in Slack story threads (Socket Mode listener)."""
    from techtrend.deliver import socket as slackbot_socket

    async def _run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        try:
            await slackbot_socket.run(stop)
        except slackbot_socket.NotConfigured as e:
            raise typer.BadParameter(str(e)) from e

    asyncio.run(_run())


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


@app.command("seed-topics")
def seed_topics_cmd(email: str = "demo@example.com") -> None:
    """Create the ten hand-written topics and subscribe a user to all of them."""
    bootstrap()
    from sqlalchemy import select

    from techtrend.personal.models import Subscription, User
    from techtrend.platform.db import session_scope
    from techtrend.shared.read.embed import embed_async
    from techtrend.topic.fingerprint import fingerprint, normalise_term
    from techtrend.topic.match import topic_embedding_input
    from techtrend.topic.models import Topic, TopicTerm
    from techtrend.topic.seed import TOPICS

    async def _go() -> None:
        async with session_scope() as s:
            user = await s.scalar(select(User).where(User.email == email))
            if user is None:
                typer.echo(f"no user {email} — run seed-demo first")
                raise typer.Exit(1)
            created = 0
            for t in TOPICS:
                fp = fingerprint(t["must"], t["should"], t["entities"], t["exclude"])
                topic = await s.scalar(select(Topic).where(Topic.fingerprint == fp))
                if topic is None:
                    (vec,) = await embed_async(
                        [topic_embedding_input(t["title"], t["must"], t["should"], t["entities"])]
                    )
                    topic = Topic(
                        fingerprint=fp,
                        title=t["title"],
                        must=t["must"],
                        should=t["should"],
                        entities=t["entities"],
                        exclude=t["exclude"],
                        embedding=vec,
                    )
                    s.add(topic)
                    await s.flush()
                    terms = {normalise_term(x) for x in (*t["must"], *t["should"], *t["entities"])}
                    for term in sorted(terms - {""}):
                        s.add(TopicTerm(term=term, topic_id=topic.id))
                    created += 1
                sub = await s.scalar(
                    select(Subscription).where(
                        Subscription.user_id == user.id, Subscription.topic_id == topic.id
                    )
                )
                if sub is None:
                    s.add(Subscription(user_id=user.id, topic_id=topic.id, label=topic.title))
                    topic.subscriber_count += 1
        typer.echo(f"topics created: {created}, user subscribed to all {len(TOPICS)}")

    asyncio.run(_go())


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
                           st.source_count, a.title, st.summary,
                           a.description, s2.name AS site_name
                      FROM stories st
                      JOIN articles a ON a.id = st.display_article_id
                      JOIN sites s2 ON s2.id = a.site_id
                     WHERE a.published_at > now() - interval '48 hours'
                     ORDER BY st.importance DESC NULLS LAST, st.source_count DESC
                     LIMIT :n
                """),
                {"n": limit},
            )
            for r in rows:
                nov = f"{r.novelty_score:.2f}" if r.novelty_score is not None else "--"
                imp = f"{r.importance:.2f}" if r.importance is not None else "--"
                typer.echo(
                    f"[{imp}] nov={nov} {(r.story_type or 'unjudged'):<20}"
                    f" {r.source_count:>2}src  {r.title[:70]}"
                )
                # Our summary when judged; else the publisher's own snippet, quoted.
                blurb = r.summary or (f'"{r.description}" — {r.site_name}' if r.description else "")
                if blurb:
                    typer.echo(f"       {blurb[:170]}")

    asyncio.run(_go())


@app.command("weekly-report")
def weekly_report_cmd(
    post: Annotated[bool, typer.Option(help="Post to the Slack channel")] = False,
    week_ending: Annotated[
        str | None, typer.Option(help="ISO date; defaults to the latest completed week")
    ] = None,
) -> None:
    """The week's news, and what it points to. Prints unless --post.

    Without --post this is a dry run: it costs one model call and posts
    nothing, which is how you read the week before the channel does.
    """
    bootstrap()
    from datetime import UTC, datetime, timedelta
    from datetime import time as _time

    from techtrend.deliver import report as rep
    from techtrend.deliver.digest import linkify
    from techtrend.deliver.slack import SlackClient, to_mrkdwn
    from techtrend.platform.db import session_scope

    s = settings()
    if not s.slack_channel:
        raise typer.BadParameter("weekly-report needs slack_channel configured")

    if week_ending:
        from datetime import date as _date

        end = _date.fromisoformat(week_ending)
        until = datetime.combine(end, _time(rep.REPORT_HOUR), tzinfo=rep.tz())
        since = until - timedelta(days=7)
    else:
        since, until = rep.week_window()

    async def _go() -> tuple[str, str | None]:
        async with session_scope() as sess:
            body, rows, totals = await rep.build(
                sess, s.slack_channel, since.astimezone(UTC), until.astimezone(UTC)
            )
        if not body:
            return "(no stories carried in this window)", None
        if not post:
            return body, None
        client = SlackClient()
        linked = await linkify(to_mrkdwn(body), rows, client, s.slack_channel)
        fallback, blocks = rep.blocks_for(until, linked, totals.n, totals.sites)
        ts = await client.post(s.slack_channel, fallback, blocks=blocks, unfurl=False)
        return body, ts

    body, ts = asyncio.run(_go())
    typer.echo(body)
    if ts:
        typer.echo(f"\nposted to {s.slack_channel} (ts={ts})")


@app.command("fingerprint-study")
def fingerprint_study_cmd() -> None:
    """THE most important measurement in the project, and it costs one query.

    If N users produce ~0.3N distinct topics the economics work; if ~N they
    don't. Run it the day there is real signup data, and keep running it.
    """
    bootstrap()
    from sqlalchemy import text as sql

    from techtrend.platform.db import session_scope

    async def _go() -> None:
        async with session_scope() as s:
            row = (
                await s.execute(
                    sql("""
                        SELECT count(*) AS subs,
                               count(DISTINCT topic_id) AS distinct_topics,
                               count(DISTINCT user_id) AS users
                          FROM subscriptions
                    """)
                )
            ).one()
            top = await s.execute(
                sql("""
                    SELECT t.title, t.subscriber_count FROM topics t
                     WHERE t.subscriber_count > 1
                     ORDER BY t.subscriber_count DESC LIMIT 10
                """)
            )
        subs, distinct, users = row.subs, row.distinct_topics, row.users
        ratio = distinct / subs if subs else 0.0
        typer.echo(f"users={users} subscriptions={subs} distinct_topics={distinct}")
        typer.echo(
            f"dedup ratio: {ratio:.2f} distinct per subscription "
            f"({'GOOD — topics collapse' if ratio < 0.5 else 'WATCH — little collapse yet'})"
        )
        for r in top:
            typer.echo(f"  shared by {r.subscriber_count}: {r.title}")

    asyncio.run(_go())


@app.command("backfill-descriptions")
def backfill_descriptions_cmd(batch: int = 200) -> None:
    """Re-extract publisher preview snippets from the stored raw HTML."""
    bootstrap()
    from techtrend.shared.read.backfill import backfill_descriptions

    n = asyncio.run(backfill_descriptions(batch))
    typer.echo(f"processed {n} articles")


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


async def _match(job: queue.Job) -> None:
    from techtrend.topic import worker as match_worker

    await match_worker.run(job)


async def _feedback(job: queue.Job) -> None:
    from techtrend.personal import learn

    await learn.run(job)


async def _notify(job: queue.Job) -> None:
    from techtrend.deliver import worker as notify_worker

    await notify_worker.run(job)


async def _digest(job: queue.Job) -> None:
    from techtrend.deliver import digest

    await digest.run(job)


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
    "match": _match,
    "feedback": _feedback,
    "notify": _notify,
    "digest": _digest,
    "maintenance": _maintenance,
}


async def _sweep_maintenance() -> None:
    """Enqueue the maintenance job. Nothing else ever will.

    `maintenance` was in HANDLERS and in the unit's --stage list from the start,
    but no code path inserted a job row -- so `reap_stale` and `purge_done` had
    never run once. The queue grew unbounded, and a worker restart orphaned
    every in-flight job permanently, because reclaiming them IS `reap_stale`.

    Keyed by time bucket, so this is idempotent across loop iterations and
    across concurrent workers: whoever gets there first inserts, the rest hit
    ON CONFLICT DO NOTHING.
    """
    bucket = int(time.time()) // settings().maintenance_interval_s
    await queue.enqueue("maintenance", f"maintenance:{bucket}", priority=PRIORITY_BACKFILL)


async def _sweep_digest() -> None:
    """Enqueue the day's digest once the local clock passes the digest hour.

    Keyed on the LOCAL DATE, so the ON CONFLICT is what makes this fire once a
    day no matter how often the loop spins -- there is no cron here, the same
    way there is no scheduler process for collection.

    The date key alone is not sufficient memory, because `purge_done` deletes
    the finished job row; `daily_digests` is the durable half, checked inside
    the stage itself.
    """
    from techtrend.deliver import digest

    if not settings().digest_enabled or not digest.is_due():
        return
    day = digest.local_day()
    await queue.enqueue(
        "digest",
        f"digest:{day.isoformat()}",
        payload={"day": day.isoformat()},
        priority=PRIORITY_BACKFILL,
    )


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

    do_maintenance = "maintenance" in stages
    do_digest = "digest" in stages

    while not stop.is_set():
        if sweep is not None:
            # The scheduler is the `next_check_at` column; this is its only reader.
            await sweep()
        if do_maintenance:
            await _sweep_maintenance()
        if do_digest:
            await _sweep_digest()
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
