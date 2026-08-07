"""The collect stage handler, and the sweep that turns due endpoints into jobs.

There is no scheduler process: `sweep_due()` is one idempotent INSERT..SELECT
that any collect worker runs on each poll. Two workers sweeping the same due
endpoint compute the same job key, and UNIQUE (stage, key) makes the second a
no-op.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from techtrend.platform import queue, telemetry
from techtrend.platform.db import session_scope
from techtrend.shared.collect import schedule
from techtrend.shared.collect.fetcher import FetchResult, PoliteFetcher, RobotsDisallowed
from techtrend.shared.collect.parse import Link, parse_feed, parse_sitemap
from techtrend.shared.collect.urls import canonical, url_hash

_fetcher: PoliteFetcher | None = None


def fetcher() -> PoliteFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = PoliteFetcher()
    return _fetcher


_SWEEP = text("""
    INSERT INTO jobs (stage, key, payload, priority)
    SELECT 'collect',
           'collect:endpoint:' || e.id || ':' || floor(extract(epoch FROM e.next_check_at)),
           jsonb_build_object('endpoint_id', e.id),
           CASE WHEN s.tier = 'A' THEN 10 ELSE 100 END
      FROM endpoints e
      JOIN sites s ON s.id = e.site_id
     WHERE e.next_check_at <= now()
       AND e.failure_streak < :parked
       AND s.opt_out_at IS NULL
     ORDER BY e.next_check_at
     LIMIT :batch
    ON CONFLICT (stage, key) DO NOTHING
""")

_LOAD = text("""
    SELECT e.id, e.url, e.kind, e.etag, e.last_modified, e.interval_s, e.quiet_streak,
           e.failure_streak, s.id AS site_id, s.tier, s.opt_out_at
      FROM endpoints e
      JOIN sites s ON s.id = e.site_id
     WHERE e.id = :id
""")

_BUMP = text("""
    UPDATE endpoints
       SET next_check_at  = now() + make_interval(secs => :interval_s),
           interval_s     = :interval_s,
           quiet_streak   = :quiet_streak,
           failure_streak = :failure_streak,
           etag           = COALESCE(:etag, etag),
           last_modified  = COALESCE(:last_modified, last_modified),
           last_status    = :status
     WHERE id = :id
""")


async def sweep_due(batch: int = 200) -> int:
    """Enqueue a collect job for every due endpoint. Safe to call from N workers."""
    async with session_scope() as s:
        result = await s.execute(_SWEEP, {"batch": batch, "parked": schedule.PARKED_FAILURE_STREAK})
        return int(getattr(result, "rowcount", 0) or 0)


async def run(job: queue.Job) -> None:
    """Check one endpoint; enqueue a read job per unseen link.

    Idempotent: read jobs are keyed by canonical URL hash, and `articles`
    has UNIQUE (url_hash) as the durable backstop.
    """
    endpoint_id = job.payload["endpoint_id"]
    async with session_scope() as s:
        ep = (await s.execute(_LOAD, {"id": endpoint_id})).one_or_none()
    if ep is None:
        return  # endpoint deleted since the sweep

    if ep.opt_out_at is not None:
        # Invariant #3: publisher opt-out gates collection at the top.
        async with session_scope() as s:
            await s.execute(
                text("UPDATE endpoints SET failure_streak = :parked WHERE id = :id"),
                {"id": ep.id, "parked": schedule.PARKED_FAILURE_STREAK},
            )
        return

    try:
        resp = await fetcher().get(ep.url, etag=ep.etag, last_modified=ep.last_modified)
    except RobotsDisallowed:
        await _record_failure(ep, status=None)
        return
    except Exception as e:
        # Network trouble is a property of the endpoint's schedule, not the
        # job: record it and complete, rather than burning queue retries.
        telemetry.log.info("collect.fetch_failed", endpoint=ep.url, error=repr(e))
        await _record_failure(ep, status=None)
        return

    if resp.not_modified:
        await _bump(ep, resp, published=False)
        return
    if resp.status != 200:
        await _record_failure(ep, status=resp.status)
        return

    links = parse_feed(resp.body) if ep.kind == "feed" else parse_sitemap(resp.body)
    fresh = await _enqueue_reads(ep, links)
    await _bump(ep, resp, published=fresh > 0)
    telemetry.log.info("collect.checked", endpoint=ep.url, links=len(links), fresh=fresh)


async def _enqueue_reads(ep: Any, links: list[Link]) -> int:
    fresh = 0
    async with session_scope() as s:
        for link in links:
            inserted = await queue.enqueue(
                "read",
                f"read:article:{url_hash(link.url).hex()}",
                {
                    "url": canonical(link.url),
                    "site_id": ep.site_id,
                    "title_hint": link.title,
                    "published_hint": link.published.isoformat() if link.published else None,
                },
                priority=10 if ep.tier == "A" else 100,
                session=s,
            )
            fresh += int(inserted)
    return fresh


async def _bump(ep: Any, resp: FetchResult, *, published: bool) -> None:
    nxt = schedule.after_check(ep.tier, ep.interval_s, ep.quiet_streak, published=published)
    async with session_scope() as s:
        await s.execute(
            _BUMP,
            {
                "id": ep.id,
                "interval_s": nxt.interval_s,
                "quiet_streak": nxt.quiet_streak,
                "failure_streak": nxt.failure_streak,
                "etag": resp.etag,
                "last_modified": resp.last_modified,
                "status": resp.status,
            },
        )


async def _record_failure(ep: Any, *, status: int | None) -> None:
    nxt = schedule.after_failure(ep.tier, ep.interval_s, ep.failure_streak)
    async with session_scope() as s:
        await s.execute(
            _BUMP,
            {
                "id": ep.id,
                "interval_s": nxt.interval_s,
                "quiet_streak": nxt.quiet_streak,
                "failure_streak": nxt.failure_streak,
                "etag": None,
                "last_modified": None,
                "status": status,
            },
        )
