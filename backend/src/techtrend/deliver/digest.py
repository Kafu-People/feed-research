"""The digest stage: one day of the channel in, one roundup message out.

Reads what was POSTED, not what was matched. The digest is a recap of the
channel a reader actually saw, so its input has to be the same set -- a digest
assembled from `matches` would summarise stories that never appeared, which
reads as the bot inventing coverage.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from techtrend.ai.client import client as ai_client
from techtrend.deliver.slack import SlackClient, to_mrkdwn
from techtrend.platform import queue, telemetry
from techtrend.platform.config import settings
from techtrend.platform.db import session_scope

# Ordered by reach then recency: when the cap bites, the widely-covered
# stories are the ones that survive into the model's view.
_DAY = text("""
    SELECT a.title, si.name AS site, sp.posted_at, sp.ts, st.source_count,
           coalesce(
               (SELECT string_agg(t.title, ', ' ORDER BY m.match_score DESC)
                  FROM matches m JOIN topics t ON t.id = m.topic_id
                 WHERE m.story_id = st.id), ''
           ) AS topics
      FROM slack_posts sp
      JOIN stories st ON st.id = sp.story_id
      JOIN articles a ON a.id = st.display_article_id
      JOIN sites si ON si.id = a.site_id
     WHERE sp.channel = :ch
       AND sp.posted_at > :since
       AND sp.posted_at <= :until
     ORDER BY st.source_count DESC, sp.posted_at DESC
     LIMIT :cap
""")

_COUNT = text("""
    SELECT count(*) AS n, count(DISTINCT a.site_id) AS sites
      FROM slack_posts sp
      JOIN stories st ON st.id = sp.story_id
      JOIN articles a ON a.id = st.display_article_id
     WHERE sp.channel = :ch AND sp.posted_at > :since AND sp.posted_at <= :until
""")

_EXISTS = text("SELECT ts FROM daily_digests WHERE day = :day AND channel = :ch")

_RECORD = text("""
    INSERT INTO daily_digests (day, channel, ts, story_count)
    VALUES (:day, :ch, :ts, :n)
    ON CONFLICT (day, channel) DO NOTHING
""")


def tz() -> ZoneInfo:
    return ZoneInfo(settings().digest_timezone)


def local_day(now: datetime | None = None) -> date:
    """The local calendar day a digest firing now would be reporting on."""
    return (now or datetime.now(UTC)).astimezone(tz()).date()


def is_due(now: datetime | None = None) -> bool:
    """True once the local clock has passed the configured hour.

    Deliberately `>=` and not an equality window: a worker that was down at
    18:00 and comes back at 18:40 should still file the day's report, and the
    `daily_digests` ledger is what stops it filing twice.
    """
    s = settings()
    return (now or datetime.now(UTC)).astimezone(tz()).hour >= s.digest_hour


def render_headlines(rows: list) -> str:
    """The model's input: numbered headlines with reach and topic, nothing else.

    No bodies and no URLs -- a day of full text would cost more than the whole
    month's budget, and the prompt is explicit that this is headline-level work.
    """
    out = []
    for i, r in enumerate(rows, 1):
        reach = f", {r.source_count} outlets" if r.source_count > 1 else ""
        topic = f" [{r.topics}]" if r.topics else ""
        out.append(f"{i}. {r.title} ({r.site}{reach}){topic}")
    return "\n".join(out)


# [phrase](12) -- the model's story reference, resolved to a permalink here.
# The number is bounded to 1-3 digits so a stray "(2026)" after a bracket cannot
# be read as a reference.
_LINK = re.compile(r"\[([^\[\]\n]{1,120})\]\((\d{1,3})\)")


async def linkify(body: str, rows: list, client: SlackClient, channel: str) -> str:
    """Turn [phrase](n) into Slack's <url|phrase>, resolving n to a permalink.

    A reference the model invented, or one whose permalink Slack declines to
    produce, degrades to the bare phrase. A digest with a dead link in it is
    worse than one with plain text, and the sentence reads fine either way.
    """
    wanted = {int(m.group(2)) for m in _LINK.finditer(body)}
    links: dict[int, str] = {}
    for n in sorted(wanted):
        if not 1 <= n <= len(rows):
            continue  # hallucinated index
        try:
            if url := await client.permalink(channel, rows[n - 1].ts):
                links[n] = url
        except Exception:  # noqa: BLE001 - a missing link must not lose the digest
            telemetry.log.warning("digest.permalink_failed", n=n)

    def sub(m: re.Match[str]) -> str:
        phrase, n = m.group(1), int(m.group(2))
        url = links.get(n)
        # Slack link text cannot contain an unescaped | or > without breaking.
        safe = phrase.replace("|", "\u2758").replace(">", "&gt;")
        return f"<{url}|{safe}>" if url else phrase

    out = _LINK.sub(sub, body)
    telemetry.log.info("digest.linked", refs=len(wanted), resolved=len(links))
    return out


def blocks_for(day: date, body: str, n: int, sites: int) -> tuple[str, list[dict]]:
    """(fallback, blocks). Fallback is the push-notification line."""
    s = settings()
    heading = f"TechTrend Daily — {day.strftime('%A, %d %B %Y')}"
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": heading, "emoji": True}}
    ]
    # Slack rejects a section over 3000 chars, so paragraphs are packed into
    # as many sections as they need rather than truncated.
    for chunk in _chunk(body, 2900):
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"{n} stories · {sites} sources · "
                        f"{s.digest_window_hours:g}h to {s.digest_hour:02d}:00 {_zone_label()}"
                    ),
                }
            ],
        }
    )
    return heading, blocks


def _zone_label() -> str:
    """The live abbreviation ('-03'), falling back to the city name."""
    abbr = datetime.now(tz()).strftime("%Z")
    return (
        abbr
        if abbr and not abbr.startswith(("+", "-"))
        else settings().digest_timezone.split("/")[-1].replace("_", " ")
    )


def _chunk(body: str, limit: int) -> list[str]:
    """Split on paragraph boundaries, never mid-sentence."""
    if len(body) <= limit:
        return [body]
    parts, cur = [], ""
    for para in body.split("\n\n"):
        if cur and len(cur) + len(para) + 2 > limit:
            parts.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return parts


async def run(job: queue.Job) -> None:
    s = settings()
    if not s.digest_enabled or s.slack_bot_token is None or not s.slack_channel:
        return
    channel = s.slack_channel

    day = date.fromisoformat(job.payload["day"]) if "day" in job.payload else local_day()
    until = datetime.now(UTC)
    since = until - timedelta(hours=s.digest_window_hours)

    async with session_scope() as sess:
        if (await sess.execute(_EXISTS, {"day": day, "ch": channel})).one_or_none():
            return  # already filed: a purge-then-resweep, or a duplicate job
        totals = (await sess.execute(_COUNT, {"ch": channel, "since": since, "until": until})).one()
        rows = (
            await sess.execute(
                _DAY,
                {"ch": channel, "since": since, "until": until, "cap": s.digest_max_stories},
            )
        ).all()

    if not rows:
        telemetry.log.info("digest.skipped", day=str(day), reason="no_stories")
        return

    body = await ai_client().digest(render_headlines(list(rows)))
    if not body:
        telemetry.log.info("digest.skipped", day=str(day), reason="empty_model_output")
        return

    client = SlackClient()
    body = await linkify(to_mrkdwn(body), list(rows), client, channel)
    fallback, blocks = blocks_for(day, body, totals.n, totals.sites)
    ts = await client.post(channel, fallback, blocks=blocks, unfurl=False)
    async with session_scope() as sess:
        await sess.execute(_RECORD, {"day": day, "ch": channel, "ts": ts, "n": totals.n})
    telemetry.log.info(
        "digest.posted", day=str(day), ts=ts, stories=totals.n, sites=totals.sites, chars=len(body)
    )
