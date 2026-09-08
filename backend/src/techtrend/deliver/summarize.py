"""The summarise stage: an interval's posted cards, summarised in ONE batch.

Split out of `notify` on 2026-09-08. The notify stage used to make a live
model call per story, immediately after posting the card. That is the most
expensive shape available: full price, one request per story, and the 998-token
system prompt re-sent every time against roughly 240 tokens of article.

Here the work is deferred and pooled instead. Every card that still has no
summary -- this hour's, and anything a previous run left behind -- goes into a
single Message Batches submission at 50% off. The card is already in the
channel by then, so the summary is a threaded reply that arrives minutes later
and nothing waits on it.

`summary_ts IS NULL` is the whole work queue. That is deliberate: it is the
same column the notify stage writes, so a story cannot be summarised twice,
and a batch that fails leaves its stories exactly where they were.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from techtrend.ai.claude import BatchPending
from techtrend.ai.client import client as ai_client
from techtrend.deliver.slack import SlackClient, to_mrkdwn
from techtrend.platform import blobs, queue, telemetry
from techtrend.platform.config import settings
from techtrend.platform.db import session_scope

# Only cards that are still unsummarised, newest first, and only where there is
# a body to summarise. The age bound matches the notify stage's own guard: a
# summary threaded under a card from three weeks ago is noise, and re-enabling
# this stage must never spend money working through the archive.
_PENDING = text("""
    SELECT sp.story_id, sp.ts, sp.channel, a.title, a.text_key
      FROM slack_posts sp
      JOIN stories st ON st.id = sp.story_id
      JOIN articles a ON a.id = st.display_article_id
     WHERE sp.summary_ts IS NULL
       AND sp.summary_attempts < :max_attempts
       AND a.text_key IS NOT NULL
       AND sp.posted_at > now() - make_interval(hours => :max_age_h)
     ORDER BY sp.posted_at DESC
     LIMIT :lim
""")

# Counted BEFORE the batch is submitted, not after it comes back. A story the
# model declines is not an error -- nothing raises, nothing retries -- so the
# only way it stops costing money every hour is for the attempt to have been
# recorded the moment it was spent.
_COUNT_ATTEMPT = text("""
    UPDATE slack_posts SET summary_attempts = summary_attempts + 1
     WHERE story_id = ANY(:ids) AND summary_ts IS NULL
""")

_RECORD_SUMMARY = text("""
    UPDATE slack_posts SET summary_ts = :ts WHERE story_id = :id AND channel = :ch
""")


async def run(job: queue.Job) -> None:
    """Submit a batch, or collect one a previous run handed forward."""
    s = settings()
    from techtrend.deliver.worker import configured

    if not configured() or not s.slack_summaries or not s.ai_summary_batch:
        return

    # A follow-up job: the batch was submitted, the poll ran out of patience.
    if batch_id := job.payload.get("batch_id"):
        await _deliver(await ai_client().collect_batch(str(batch_id)), batch_id=str(batch_id))
        return

    async with session_scope() as sess:
        rows = (
            await sess.execute(
                _PENDING,
                {
                    "max_age_h": s.slack_summary_max_age_hours,
                    "lim": s.ai_summary_batch_max,
                    "max_attempts": s.slack_summary_max_attempts,
                },
            )
        ).all()
    if not rows:
        return

    items: list[tuple[int, str, str]] = []
    targets: dict[int, tuple[str, str]] = {}
    for r in rows:
        try:
            body = (await asyncio.to_thread(blobs.get, r.text_key)).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - a missing blob is one story, not the batch
            telemetry.log.warning("summarize.blob_missing", story_id=r.story_id)
            continue
        if len(body) < s.slack_summary_min_chars:
            # Thin extraction: a nav menu summarised is worse than no summary.
            telemetry.log.info(
                "summarize.skipped", story_id=r.story_id, reason="thin_text", chars=len(body)
            )
            continue
        items.append((r.story_id, r.title, body))
        targets[r.story_id] = (r.channel, r.ts)

    if not items:
        return

    async with session_scope() as sess:
        await sess.execute(_COUNT_ATTEMPT, {"ids": [sid for sid, _, _ in items]})

    telemetry.log.info("summarize.batch_start", n=len(items))
    try:
        summaries = await ai_client().summarize_batch(items)
    except BatchPending as pending:
        # The receipt, not a failure. Hand the id forward and free the worker.
        await queue.enqueue(
            "summarize",
            f"summarize:collect:{pending.batch_id}",
            {"batch_id": pending.batch_id},
            delay_s=s.ai_batch_poll_s,
        )
        telemetry.log.info("summarize.deferred", batch_id=pending.batch_id, n=len(items))
        return

    await _deliver(summaries, targets=targets)


async def _deliver(
    summaries: dict[int, str | None],
    *,
    targets: dict[int, tuple[str, str]] | None = None,
    batch_id: str | None = None,
) -> None:
    """Thread each summary under its card and record it.

    Per story, not per batch: one Slack failure must not cost the other
    summaries in the same submission, which have already been paid for.
    """
    if targets is None:
        targets = await _targets_for(list(summaries))
    client = SlackClient()
    posted = 0
    for story_id, summary in summaries.items():
        target = targets.get(story_id)
        if target is None:
            continue
        channel, thread_ts = target
        if not summary:
            # The model declined. Nothing to post, and `summary_ts` stays NULL
            # -- which means the next run retries it. That is cheap and right:
            # a re-extracted body may summarise where the first one did not.
            telemetry.log.info("summarize.declined", story_id=story_id)
            continue
        try:
            ts = await client.post(channel, to_mrkdwn(summary), thread_ts=thread_ts)
            async with session_scope() as sess:
                await sess.execute(_RECORD_SUMMARY, {"id": story_id, "ch": channel, "ts": ts})
            posted += 1
        except Exception:  # noqa: BLE001 - one summary, never the batch
            telemetry.log.exception("summarize.post_failed", story_id=story_id)
    telemetry.log.info("summarize.batch_done", posted=posted, batch_id=batch_id)


async def _targets_for(story_ids: list[int]) -> dict[int, tuple[str, str]]:
    """Where each summary goes, for the collect path that has no local state."""
    if not story_ids:
        return {}
    async with session_scope() as sess:
        rows = (
            await sess.execute(
                text(
                    "SELECT story_id, channel, ts FROM slack_posts"
                    " WHERE story_id = ANY(:ids) AND summary_ts IS NULL"
                ),
                {"ids": story_ids},
            )
        ).all()
    return {r.story_id: (r.channel, r.ts) for r in rows}
