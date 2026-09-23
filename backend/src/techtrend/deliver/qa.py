"""Answering questions asked in a story thread.

The transport is `deliver.socket`; everything decided here is pure enough to
test without a WebSocket or a Slack workspace.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

from techtrend.ai.client import client as ai_client
from techtrend.deliver.slack import SlackClient, to_mrkdwn
from techtrend.platform import blobs, telemetry
from techtrend.platform.config import settings
from techtrend.platform.db import session_scope

# A thread's parent ts is the card's ts, which is how a mention finds its story.
# MANY rows, not one. In cards mode a `ts` is one story's card; in hourly mode
# it is the report, and every story in that hour shares it. This used to be
# read with `.one_or_none()`, which raises MultipleResultsFound on a report --
# so every question asked under an hourly report died before reaching the
# model. Ordered so the context is stable between two askings of the same
# question.
_STORIES_FOR_THREAD = text("""
    SELECT st.id, a.title, a.text_key, s.name AS site
      FROM slack_posts p
      JOIN stories st ON st.id = p.story_id
      JOIN articles a ON a.id = st.display_article_id
      JOIN sites s ON s.id = a.site_id
     WHERE p.ts = :ts
       AND s.opt_out_at IS NULL
     ORDER BY st.source_count DESC, st.id
""")

_MENTION = re.compile(r"<@[A-Z0-9]+>")
_WS = re.compile(r"\s+")

NOT_A_STORY_THREAD = (
    "Ask me inside a story thread and I'll answer from that article. "
    "I don't have anything to go on out here."
)
NO_QUESTION = "Ask me something about this story and I'll answer from the article."


def strip_mentions(raw: str) -> str:
    """`<@U123> what does this mean?` -> `what does this mean?`

    Whitespace is collapsed afterwards: a mention removed from mid-sentence
    otherwise leaves a gap in the question we hand the model.
    """
    return _WS.sub(" ", _MENTION.sub(" ", raw or "")).strip()


def render_thread(
    messages: list[dict[str, Any]], *, bot_id: str | None, skip_ts: str | None
) -> str:
    """Flatten a thread for the prompt.

    Without `users:read` we cannot resolve display names, and asking for that
    scope to label chat lines is not worth it -- who said it matters far less
    than what was said, and the bot's own turns are identifiable by bot_id.
    """
    lines = []
    for m in messages:
        if skip_ts and m.get("ts") == skip_ts:
            continue  # the question itself is passed separately
        body = strip_mentions(m.get("text") or "")
        if not body:
            continue
        who = "TechTrend" if bot_id and m.get("bot_id") == bot_id else "someone"
        lines.append(f"{who}: {body}")
    return "\n".join(lines)


async def handle_mention(
    client: SlackClient, event: dict[str, Any], *, bot_id: str | None = None
) -> None:
    """Answer one @mention. Never raises: the listener must survive a bad event."""
    s = settings()
    channel = str(event.get("channel") or "")
    ts = str(event.get("ts") or "")
    thread_ts = str(event.get("thread_ts") or "")
    question = strip_mentions(str(event.get("text") or ""))
    if not channel or not ts:
        telemetry.log.info("qa.ignored", reason="event missing channel or ts")
        return

    try:
        # A mention outside a thread has no article behind it. Reply in a
        # thread on their own message rather than posting to the channel.
        if not thread_ts:
            await client.post(channel, NOT_A_STORY_THREAD, thread_ts=ts)
            return
        if not question:
            await client.post(channel, NO_QUESTION, thread_ts=thread_ts)
            return

        async with session_scope() as sess:
            rows = (await sess.execute(_STORIES_FOR_THREAD, {"ts": thread_ts})).all()
        if not rows:
            await client.post(channel, NOT_A_STORY_THREAD, thread_ts=thread_ts)
            return

        title, body = await _context(rows, budget=s.slack_qa_max_body_chars)

        msgs = await client.replies(channel, thread_ts, limit=s.slack_qa_max_thread_msgs)
        thread = render_thread(msgs, bot_id=bot_id, skip_ts=ts)

        reply = await ai_client().answer(question, title, body, thread)
        await client.post(channel, to_mrkdwn(reply), thread_ts=thread_ts)
        telemetry.log.info(
            "qa.answered",
            story_ids=[r.id for r in rows],
            chars=len(reply),
            question_chars=len(question),
        )
    except Exception:  # noqa: BLE001 - one bad question must not kill the listener
        telemetry.log.exception("qa.failed", thread_ts=thread_ts)
        try:
            await client.post(
                channel,
                "Something went wrong answering that. Try again?",
                thread_ts=thread_ts or ts,
            )
        except Exception:  # noqa: BLE001 - Slack itself may be the failure
            telemetry.log.exception("qa.failed_to_report", thread_ts=thread_ts)


async def _context(rows: Sequence[Any], *, budget: int) -> tuple[str, str]:
    """(title, body) for the model, whether the thread is one story or a report.

    One story keeps exactly the old shape -- cards mode must not change. A
    report gets every story it carried, each labelled, with the body budget
    split between them: a question under a report is as often "which of these
    matters" as it is about one of them, so the titles all have to be present
    even when there is no room for much text under each.
    """
    if len(rows) == 1:
        return rows[0].title, await _body(rows[0], budget)

    share = max(400, budget // len(rows))
    parts = []
    for i, r in enumerate(rows, 1):
        text_ = await _body(r, share)
        parts.append(f"[{i}] {r.title} ({r.site})" + (f"\n{text_}" if text_ else ""))
    return f"TechTrend hourly report \u2014 {len(rows)} stories", "\n\n".join(parts)


async def _body(row: object, budget: int) -> str:
    """The stored article text, truncated. Missing blob is not fatal: the
    title alone still answers some questions, and a dead blob must not turn
    into a non-answer for every other story in the same report."""
    key = getattr(row, "text_key", None)
    if not key:
        return ""
    try:
        raw = await asyncio.to_thread(blobs.get, key)
    except Exception:  # noqa: BLE001 - one story's text, not the answer
        telemetry.log.warning("qa.blob_missing", story_id=getattr(row, "id", None))
        return ""
    return raw.decode("utf-8", "replace")[:budget]
