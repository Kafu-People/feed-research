"""Collect against real Postgres: sweep -> claim -> enqueue reads -> bump schedule."""

from __future__ import annotations

import pytest
import respx
from sqlalchemy import text

from techtrend.platform import queue
from techtrend.platform.db import session_scope
from techtrend.shared.collect import worker
from techtrend.shared.collect.seed import seed_sites

pytestmark = pytest.mark.integration

FEED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>One</title><link>https://ex.com/one?utm_source=rss</link></item>
<item><title>Two</title><link>https://ex.com/two</link></item>
</channel></rss>"""


async def _make_endpoint(tier: str = "A") -> int:
    async with session_scope() as s:
        site_id = (
            await s.execute(
                text(
                    "INSERT INTO sites (domain, name, tier) VALUES ('ex.com', 'Ex', :t)"
                    " RETURNING id"
                ),
                {"t": tier},
            )
        ).scalar_one()
        return (
            await s.execute(
                text(
                    "INSERT INTO endpoints (site_id, url, kind, interval_s)"
                    " VALUES (:sid, 'https://ex.com/feed', 'feed', 120) RETURNING id"
                ),
                {"sid": site_id},
            )
        ).scalar_one()


@pytest.fixture(autouse=True)
def fresh_fetcher() -> None:
    worker._fetcher = None  # robots cache must not leak between tests


async def test_sweep_enqueues_due_endpoints_idempotently() -> None:
    ep_id = await _make_endpoint()
    assert await worker.sweep_due() == 1
    assert await worker.sweep_due() == 0  # same due time -> same key -> no-op
    jobs = await queue.claim(["collect"])
    assert len(jobs) == 1
    assert jobs[0].payload == {"endpoint_id": ep_id}
    assert jobs[0].key.startswith(f"collect:endpoint:{ep_id}:")


@respx.mock
async def test_collect_run_enqueues_reads_and_bumps_schedule() -> None:
    await _make_endpoint()
    respx.get("https://ex.com/robots.txt").respond(404)
    respx.get("https://ex.com/feed").respond(200, content=FEED, headers={"ETag": '"v1"'})
    await worker.sweep_due()
    (job,) = await queue.claim(["collect"])
    await worker.run(job)

    reads = await queue.claim(["read"], batch=10)
    urls = sorted(j.payload["url"] for j in reads)
    assert urls == ["https://ex.com/one", "https://ex.com/two"]  # canonicalised

    async with session_scope() as s:
        ep = (
            await s.execute(
                text("SELECT etag, next_check_at > now() AS scheduled, quiet_streak FROM endpoints")
            )
        ).one()
    assert ep.etag == '"v1"'
    assert ep.scheduled
    assert ep.quiet_streak == 0


@respx.mock
async def test_rerun_is_idempotent_and_304_counts_as_quiet() -> None:
    await _make_endpoint()
    respx.get("https://ex.com/robots.txt").respond(404)
    feed_route = respx.get("https://ex.com/feed")
    feed_route.respond(200, content=FEED)

    await worker.sweep_due()
    (job,) = await queue.claim(["collect"])
    await worker.run(job)
    n_before = len(await queue.claim(["read"], batch=10))

    feed_route.respond(304)
    await worker.run(job)  # re-delivery of the same job
    async with session_scope() as s:
        n_after = (
            await s.execute(text("SELECT count(*) FROM jobs WHERE stage = 'read'"))
        ).scalar_one()
        quiet = (await s.execute(text("SELECT quiet_streak FROM endpoints"))).scalar_one()
    assert n_before == 2
    assert n_after == 2  # nothing duplicated
    assert quiet == 1


async def test_opted_out_site_is_never_swept() -> None:
    await _make_endpoint()
    async with session_scope() as s:
        await s.execute(text("UPDATE sites SET opt_out_at = now()"))
    assert await worker.sweep_due() == 0  # invariant #3 gates at the sweep


@respx.mock
async def test_fetch_failure_backs_off_not_retries() -> None:
    await _make_endpoint()
    respx.get("https://ex.com/robots.txt").respond(404)
    respx.get("https://ex.com/feed").respond(500)
    await worker.sweep_due()
    (job,) = await queue.claim(["collect"])
    await worker.run(job)  # completes without raising: schedule owns the retry
    async with session_scope() as s:
        ep = (
            await s.execute(
                text(
                    "SELECT failure_streak, last_status,"
                    " next_check_at > now() AS later FROM endpoints"
                )
            )
        ).one()
    assert ep.failure_streak == 1
    assert ep.last_status == 500
    assert ep.later


async def test_seed_sites_is_idempotent() -> None:
    out1 = await seed_sites()
    out2 = await seed_sites()
    assert out1["sites"] == out2["sites"] > 50
    async with session_scope() as s:
        n_sites = (await s.execute(text("SELECT count(*) FROM sites"))).scalar_one()
        n_eps = (await s.execute(text("SELECT count(*) FROM endpoints"))).scalar_one()
    assert n_sites == out1["sites"]
    assert n_eps == out1["endpoints"]
