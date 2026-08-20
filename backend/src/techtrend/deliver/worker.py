"""The notify stage: one matched story in, one Slack message out.

Selection lives here rather than at the enqueue site so that the floor and the
topic filter can be retuned without a queue drain -- a job already in flight is
re-checked against current settings the moment it runs.
"""

from __future__ import annotations

from sqlalchemy import text

from techtrend.deliver.slack import SlackClient, followup_text, story_blocks
from techtrend.platform import queue, telemetry
from techtrend.platform.config import settings
from techtrend.platform.db import session_scope

# Invariant #3: a publisher opt-out gates serving, and Slack is serving.
_LOAD = text("""
    SELECT st.id, st.source_count, a.title, a.url, a.published_at, s.name AS site
      FROM stories st
      JOIN articles a ON a.id = st.display_article_id
      JOIN sites s ON s.id = a.site_id
     WHERE st.id = :id
       AND s.opt_out_at IS NULL
""")

_TOPICS = text("""
    SELECT t.title, m.match_score
      FROM matches m JOIN topics t ON t.id = m.topic_id
     WHERE m.story_id = :id
       AND m.match_score >= :floor
       AND (:unfiltered OR m.topic_id = ANY(:topic_ids))
     ORDER BY m.match_score DESC
""")

_EXISTING = text("SELECT ts, source_count FROM slack_posts WHERE story_id = :id AND channel = :ch")

_RECORD = text("""
    INSERT INTO slack_posts (story_id, channel, ts, source_count)
    VALUES (:id, :ch, :ts, :n)
    ON CONFLICT (story_id, channel) DO NOTHING
""")

_BUMP = text("UPDATE slack_posts SET source_count = :n WHERE story_id = :id AND channel = :ch")


def configured() -> bool:
    """Both halves or nothing -- a token without a channel posts into the void."""
    s = settings()
    return s.slack_bot_token is not None and bool(s.slack_channel)


async def run(job: queue.Job) -> None:
    s = settings()
    if not configured():
        return  # switched off since the job was enqueued: a no-op, not a failure

    story_id = job.payload["story_id"]
    channel = s.slack_channel
    assert channel is not None  # noqa: S101 - narrowed by configured()

    async with session_scope() as sess:
        row = (await sess.execute(_LOAD, {"id": story_id})).one_or_none()
        if row is None:
            return  # deleted, or the publisher opted out after the match
        topics = (
            await sess.execute(
                _TOPICS,
                {
                    "id": story_id,
                    "floor": s.slack_match_floor,
                    "unfiltered": not s.slack_topic_ids,
                    "topic_ids": list(s.slack_topic_ids),
                },
            )
        ).all()
        existing = (await sess.execute(_EXISTING, {"id": story_id, "ch": channel})).one_or_none()

    if not topics:
        # Re-scored below the floor, or the topic filter narrowed since enqueue.
        telemetry.log.info("notify.skipped", story_id=story_id, reason="no_qualifying_topic")
        return

    # An age guard, so that re-enabling the stage -- or a topic backfill -- can
    # never dump last month's corpus into the channel.
    age_h = (row.published_at and _hours_since(row.published_at)) or 0.0
    if age_h > s.slack_max_age_hours:
        telemetry.log.info(
            "notify.skipped", story_id=story_id, reason="too_old", age_h=round(age_h)
        )
        return

    client = SlackClient()

    if existing is None:
        fallback, blocks = story_blocks(
            title=row.title,
            url=row.url,
            site=row.site,
            source_count=row.source_count,
            topics=[t.title for t in topics],
        )
        ts = await client.post(channel, fallback, blocks=blocks)
        async with session_scope() as sess:
            await sess.execute(
                _RECORD, {"id": story_id, "ch": channel, "ts": ts, "n": row.source_count}
            )
        telemetry.log.info(
            "notify.posted",
            story_id=story_id,
            channel=channel,
            sources=row.source_count,
            score=round(float(topics[0].match_score), 3),
        )
        return

    # Already announced. A story that has since gained sources earns one
    # threaded follow-up per new count, never a second top-level message.
    if row.source_count <= existing.source_count:
        return
    await client.post(channel, followup_text(row.source_count), thread_ts=existing.ts)
    async with session_scope() as sess:
        await sess.execute(_BUMP, {"id": story_id, "ch": channel, "n": row.source_count})
    telemetry.log.info(
        "notify.followup", story_id=story_id, channel=channel, sources=row.source_count
    )


def _hours_since(when: object) -> float:
    from datetime import UTC, datetime

    if not isinstance(when, datetime):
        return 0.0
    ref = when if when.tzinfo else when.replace(tzinfo=UTC)
    return (datetime.now(UTC) - ref).total_seconds() / 3600.0
