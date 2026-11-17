"""The hourly report: an hour of matches in, ONE message out.

Replaces the per-story card. The card model posted a message the moment a
story qualified, then threaded a summary under it minutes later -- roughly
4.4 messages an hour for 2.2 stories, and a reader scrolling back saw the
summaries detached from the headlines they belonged to.

Here the hour is the unit. One message carries every story the hour matched:
headline as the link, publisher and topics beside it, and the summary directly
underneath. Summaries come back from ONE batch submission, so the model is
called once an hour no matter how many stories the hour found.

What this gives up, deliberately and at the operator's instruction: a story no
longer has its own thread, so the Q&A listener (`deliver/socket.py`) has
nothing to answer under, and a story that gains sources has nowhere to post
its follow-up. `slack_delivery_mode = "cards"` restores both.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from techtrend.ai.claude import BatchPending
from techtrend.ai.client import client as ai_client
from techtrend.deliver.slack import Block, SlackClient, decode_title, to_mrkdwn
from techtrend.platform import blobs, queue, telemetry
from techtrend.platform.config import settings, site_blocked
from techtrend.platform.db import session_scope
from techtrend.topic.match import blocked, searchable

# Every story matched in the window, with the topics that caught it. Filtering
# by floor happens in Python for the reason the notify stage gives: the bar is
# per topic, and a CASE expression over a settings dict is worse than a
# comprehension. `slack_posts` is still the dedup -- a story already reported
# in an earlier hour never appears in a second one.
_WINDOW = text("""
    SELECT st.id, st.source_count, coalesce(st.importance, 0) AS importance,
           a.title, a.url, a.description, a.entities,
           a.published_at, a.text_key, a.site_id, si.name AS site, si.domain,
           array_agg(t.id ORDER BY m.match_score DESC) AS topic_ids,
           array_agg(t.title ORDER BY m.match_score DESC) AS topic_titles,
           array_agg(m.match_score ORDER BY m.match_score DESC) AS scores
      FROM matches m
      JOIN topics t ON t.id = m.topic_id
      JOIN stories st ON st.id = m.story_id
      JOIN articles a ON a.id = st.display_article_id
      JOIN sites si ON si.id = a.site_id
     WHERE m.matched_at > :since
       AND m.matched_at <= :until
       AND si.opt_out_at IS NULL
       AND (:unfiltered OR m.topic_id = ANY(:topic_ids))
       AND NOT EXISTS (SELECT 1 FROM slack_posts sp WHERE sp.story_id = st.id)
     GROUP BY st.id, st.source_count, st.importance, a.title, a.url, a.description,
              a.entities, a.published_at, a.text_key, a.site_id, si.name, si.domain
     ORDER BY max(m.match_score) DESC, st.source_count DESC
     LIMIT :cap
""")

# The collect path addresses the batch's OWN stories by id. Re-deriving them
# from the window would be a different set the moment a floor changes or
# another path posts one of them -- and the summaries in hand were paid for
# against this list, not that one.
_BY_IDS = text("""
    SELECT st.id, st.source_count, coalesce(st.importance, 0) AS importance,
           a.title, a.url, a.description, a.site_id, si.name AS site,
           array_agg(t.title ORDER BY m.match_score DESC) AS topic_titles
      FROM matches m
      JOIN topics t ON t.id = m.topic_id
      JOIN stories st ON st.id = m.story_id
      JOIN articles a ON a.id = st.display_article_id
      JOIN sites si ON si.id = a.site_id
     WHERE st.id = ANY(:ids)
       AND NOT EXISTS (SELECT 1 FROM slack_posts sp WHERE sp.story_id = st.id)
     GROUP BY st.id, st.source_count, st.importance, a.title, a.url, a.description,
              a.site_id, si.name
     ORDER BY max(m.match_score) DESC
""")
# Editions mode: the edition message is `ts`, the story's own thread reply is
# `summary_ts` -- which is what a 👍 / 👎 is matched back to.
_RECORD_STORY = text("""
    INSERT INTO slack_posts (story_id, channel, ts, source_count, summary_ts, summary_attempts)
    VALUES (:id, :ch, :ts, :n, :reply, 1)
    ON CONFLICT (story_id, channel) DO NOTHING
""")
EDITION_CAP = 60

_RECORD = text("""
    INSERT INTO slack_posts (story_id, channel, ts, source_count, summary_ts, summary_attempts)
    VALUES (:id, :ch, :ts, :n, :ts, 1)
    ON CONFLICT (story_id, channel) DO NOTHING
""")


def _hours_since(when: datetime) -> float:
    ref = when if when.tzinfo else when.replace(tzinfo=UTC)
    return (datetime.now(UTC) - ref).total_seconds() / 3600.0


async def _window(since: datetime, until: datetime, cap: int, floor_for: Any) -> list[Any]:
    """Unposted matches in (since, until], through every content gate."""
    s = settings()
    async with session_scope() as sess:
        rows = (
            await sess.execute(
                _WINDOW,
                {
                    "since": since,
                    "until": until,
                    "unfiltered": not s.slack_topic_ids,
                    "topic_ids": list(s.slack_topic_ids),
                    "cap": cap,
                },
            )
        ).all()
    keep = []
    for r in rows:
        # The same three gates the card path applies, re-checked here because
        # this is now the last thing between a match row and the channel.
        if site_blocked(r.domain, s.blocked_sites):
            continue
        if blocked(searchable(r.title, r.description, list(r.entities or [])), s.block_terms):
            continue
        if r.published_at and _hours_since(r.published_at) > s.slack_max_age_hours:
            continue
        if not any(
            score >= floor_for(tid) for tid, score in zip(r.topic_ids, r.scores, strict=True)
        ):
            continue
        keep.append(r)
    return keep


def rank(rows: list[Any], by_cat: dict[str, float], by_site: dict[int, float]) -> list[Any]:
    """Most important first: importance, plus reach, plus the team's feedback."""
    from techtrend.deliver.reactions import boost_for

    def score(r: Any) -> float:
        reach = 0.05 * max(0, int(r.source_count) - 1)
        return float(r.importance or 0) + reach + boost_for(r, by_cat, by_site)

    return sorted(rows, key=score, reverse=True)


async def _edition(payload: dict[str, Any], channel: str) -> None:
    """One edition: every unposted story since the previous edition, ranked."""
    from techtrend.deliver.worker import floor_for

    until = datetime.now(UTC)
    since = datetime.fromisoformat(str(payload["since"]))
    keep = await _window(since, until, EDITION_CAP, floor_for)
    if not keep:
        telemetry.log.info("edition.empty", edition=payload.get("edition"))
        return
    summaries = await _summaries(keep, since=since, until=until, extra=payload)
    if summaries is None:
        return  # deferred; the follow-up job posts the edition
    await _post_edition(keep, summaries, payload, channel)


async def _post_edition(
    rows: list[Any], summaries: dict[int, str | None], payload: dict[str, Any], channel: str
) -> None:
    from techtrend.deliver import news_format as nf
    from techtrend.deliver.reactions import boosts

    s = settings()
    try:
        by_cat, by_site = await boosts()
    except Exception:  # noqa: BLE001 - feedback is a nudge, never a blocker
        telemetry.log.warning("edition.boosts_failed", exc_info=True)
        by_cat, by_site = {}, {}
    ranked = rank(rows, by_cat, by_site)
    fallback, blocks = nf.edition_blocks(
        name=str(payload.get("edition") or "Edition"),
        when=str(payload.get("when") or ""),
        rows=ranked,
        summaries=summaries,
        top=s.edition_channel_top,
    )
    client = SlackClient()
    ts = await client.post(channel, fallback, blocks=blocks, unfurl=False)
    await _thread_and_record(client, channel, ts, ranked, summaries)
    telemetry.log.info("edition.posted", ts=ts, stories=len(ranked), edition=payload.get("edition"))


async def _thread_and_record(
    client: SlackClient,
    channel: str,
    ts: str,
    rows: list[Any],
    summaries: dict[int, str | None],
) -> None:
    """One reply per story under `ts`, each recorded as that story's post."""
    from techtrend.deliver import news_format as nf

    for r in rows:
        reply: str | None = None
        try:
            text_, blocks = nf.story_reply_blocks(r, summaries.get(r.id))
            reply = await client.post(channel, text_, blocks=blocks, thread_ts=ts, unfurl=False)
        except Exception:  # noqa: BLE001 - one reply, never the edition
            telemetry.log.warning("edition.reply_failed", story=r.id, exc_info=True)
        # Recorded even when its reply failed: the story WAS posted in the
        # edition, and recording is what keeps it out of the next one.
        async with session_scope() as sess:
            await sess.execute(
                _RECORD_STORY,
                {"id": r.id, "ch": channel, "ts": ts, "n": r.source_count, "reply": reply or ts},
            )


BREAKING_LOOKBACK_HOURS = 3


async def _breaking(channel: str) -> None:
    """Post, now, any unposted story covered widely enough not to wait."""
    from techtrend.deliver import news_format as nf
    from techtrend.deliver.worker import floor_for

    s = settings()
    until = datetime.now(UTC)
    since = until - timedelta(hours=BREAKING_LOOKBACK_HOURS)
    rows = [
        r
        for r in await _window(since, until, EDITION_CAP, floor_for)
        if r.source_count >= s.breaking_min_outlets
        and float(r.importance or 0) >= s.breaking_min_importance
    ]
    if not rows:
        return
    client = SlackClient()
    for r in rows:
        summary = await _one_summary(r)
        fallback, blocks = nf.breaking_blocks(r, summary)
        ts = await client.post(channel, fallback, blocks=blocks, unfurl=False)
        await _thread_and_record(client, channel, ts, [r], {r.id: summary})
        telemetry.log.info("breaking.posted", ts=ts, story=r.id, outlets=r.source_count)


async def _one_summary(r: Any) -> str | None:
    """A single summary, now -- a breaking story cannot wait for a batch."""
    s = settings()
    if not s.slack_summaries or not r.text_key:
        return None
    try:
        body = (await asyncio.to_thread(blobs.get, r.text_key)).decode("utf-8", "replace")
        if len(body) < s.slack_summary_min_chars:
            return None
        return await ai_client().summarize(r.title, body)
    except Exception:  # noqa: BLE001 - the headline is worth posting without prose
        telemetry.log.warning("breaking.summary_failed", story=r.id, exc_info=True)
        return None


async def run(job: queue.Job) -> None:
    from techtrend.deliver.worker import configured, floor_for

    s = settings()
    if not configured() or s.slack_delivery_mode not in ("hourly", "editions"):
        return
    channel = s.slack_channel
    assert channel is not None  # noqa: S101 - narrowed by configured()

    # A follow-up job carries the batch that outlived its poll, and the window
    # it was built from -- the clock has moved on, and re-deriving the window
    # here would report a different hour than the one the batch describes.
    if pending_batch := job.payload.get("batch_id"):
        await _collect(str(pending_batch), job.payload, channel)
        return

    if s.slack_delivery_mode == "editions":
        if job.payload.get("edition"):
            await _edition(job.payload, channel)
        else:
            await _breaking(channel)  # the hourly tick, in editions mode
        return

    until = datetime.now(UTC)
    since = until - timedelta(hours=s.slack_post_interval_hours or 1.0)
    keep = await _window(since, until, s.hourly_max_stories, floor_for)

    if not keep:
        telemetry.log.info("hourly.empty", since=since.isoformat())
        return

    summaries = await _summaries(keep, since=since, until=until)
    if summaries is None:
        return  # deferred; a follow-up job will do it

    fallback, blocks = _render(keep, summaries, since, until)
    client = SlackClient()
    # unfurl off: a dozen publisher previews would bury the report's own text,
    # and the summary already says what the preview would.
    ts = await client.post(channel, fallback, blocks=blocks, unfurl=False)

    async with session_scope() as sess:
        for r in keep:
            await sess.execute(_RECORD, {"id": r.id, "ch": channel, "ts": ts, "n": r.source_count})
    telemetry.log.info("hourly.posted", ts=ts, stories=len(keep), channel=channel)


async def _collect(batch_id: str, payload: dict[str, Any], channel: str) -> None:
    """Finish a report whose batch outlived the poll.

    Checks status ONCE and reschedules itself if the batch is still running.
    It used to call the blocking `collect_batch`, which raised `BatchPending`
    out of the job -- so a slow batch read as a job failure, retried on the
    queue's error backoff, and burned its five attempts. On 2026-09-08 a
    40-minute batch succeeded on the fifth and last one: a report that had
    already been paid for was one delay away from dead-lettering.
    """
    s = settings()
    if not await ai_client().batch_ended(batch_id):
        tries = int(payload.get("tries", 1))
        if tries >= s.ai_batch_max_polls:
            telemetry.log.warning("hourly.batch_abandoned", batch_id=batch_id, tries=tries)
            return
        await queue.enqueue(
            "hourly",
            f"hourly:collect:{batch_id}:{tries + 1}",
            {**payload, "tries": tries + 1},
            delay_s=s.ai_batch_poll_s * 6,
        )
        return

    summaries = await ai_client().read_batch(batch_id)
    ids = [int(i) for i in payload.get("story_ids", [])]
    async with session_scope() as sess:
        rows = list((await sess.execute(_BY_IDS, {"ids": ids})).all())
    if not rows:
        telemetry.log.info("hourly.collect_empty", batch_id=batch_id)
        return
    if payload.get("edition"):
        await _post_edition(rows, summaries, payload, channel)
        return
    since = datetime.fromisoformat(str(payload["since"]))
    until = datetime.fromisoformat(str(payload["until"]))
    fallback, blocks = _render(rows, summaries, since, until)
    client = SlackClient()
    ts = await client.post(channel, fallback, blocks=blocks, unfurl=False)
    async with session_scope() as sess:
        for r in rows:
            await sess.execute(_RECORD, {"id": r.id, "ch": channel, "ts": ts, "n": r.source_count})
    telemetry.log.info("hourly.posted", ts=ts, stories=len(rows), batch_id=batch_id)


async def _summaries(
    rows: list[Any], *, since: datetime, until: datetime, extra: dict[str, Any] | None = None
) -> dict[int, str | None] | None:
    """One batch for the hour. None means "deferred, not failed"."""
    s = settings()
    if not s.slack_summaries:
        return {}
    items: list[tuple[int, str, str]] = []
    for r in rows:
        if not r.text_key:
            continue
        try:
            body = (await asyncio.to_thread(blobs.get, r.text_key)).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - one story, not the report
            telemetry.log.warning("hourly.blob_missing", story_id=r.id)
            continue
        if len(body) >= s.slack_summary_min_chars:
            items.append((r.id, r.title, body))
    if not items:
        return {}
    try:
        return await ai_client().summarize_batch(items)
    except BatchPending as pending:
        # The report waits for its summaries rather than posting without them:
        # a roundup of bare links is the thing this design exists to replace.
        await queue.enqueue(
            "hourly",
            f"hourly:collect:{pending.batch_id}",
            {
                **(extra or {}),
                "batch_id": pending.batch_id,
                "since": since.isoformat(),
                "until": until.isoformat(),
                # Every story, not only the summarised ones: an edition posts
                # them all, with or without prose.
                "story_ids": [r.id for r in rows] if extra else [sid for sid, _, _ in items],
            },
            delay_s=s.ai_batch_poll_s,
        )
        telemetry.log.info("hourly.deferred", batch_id=pending.batch_id, n=len(items))
        return None
    except Exception:  # noqa: BLE001 - the links are worth posting without prose
        telemetry.log.exception("hourly.summaries_failed")
        return {}


def _render(
    rows: list[Any], summaries: dict[int, str | None], since: datetime, until: datetime
) -> tuple[str, list[Block]]:
    """(fallback, blocks). One section per story: link, source line, summary."""
    label = until.strftime("%H:%M")
    heading = f"TechTrend — the last hour ({len(rows)} {'story' if len(rows) == 1 else 'stories'})"
    blocks: list[Block] = [
        {"type": "header", "text": {"type": "plain_text", "text": heading, "emoji": True}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"{since.strftime('%H:%M')}–{label} UTC"}],
        },
    ]
    for r in rows:
        # Decode BEFORE escaping. Publisher titles arrive with their entities
        # intact ("Here&#8217;s"), and escaping one of those directly ships a
        # literal "&amp;#8217;" to the channel -- the same trap `_esc` in
        # slack.py documents. Slack link text also breaks on a bare | or >.
        safe = decode_title(r.title).replace("|", "❘").replace(">", "&gt;")
        reach = f" · {r.source_count} outlets" if r.source_count > 1 else ""
        topics = ", ".join(dict.fromkeys(r.topic_titles))
        line = f"*<{r.url}|{safe}>*\n_{r.site}{reach} · {topics}_"
        if summary := summaries.get(r.id):
            line += f"\n{to_mrkdwn(summary)}"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line}})
        blocks.append({"type": "divider"})
    if blocks and blocks[-1]["type"] == "divider":
        blocks.pop()

    # The push-notification line: what a reader sees before opening Slack.
    titles = "; ".join(decode_title(r.title) for r in rows[:3])
    fallback = f"{heading} — {titles}"
    return fallback[:2000], blocks
