"""The weekly stage: seven days of the channel in, one Saturday roundup out.

The daily digest says what happened that day. This says what the WEEK meant,
and then what it points to -- the arc that only shows up across seven days,
plus a forecast the reader can check later.

Reads what was POSTED, not what was matched, for the same reason the digest
does: the roundup recaps the channel a reader actually saw, and one assembled
from `matches` would summarise stories that never appeared.

Both content gates run on the headlines BEFORE the model sees them. A blocked
story that reaches the prompt comes back out inside the prose, where no later
gate is looking -- so the gate has to sit in front of the model, not behind it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from techtrend.ai.client import client as ai_client
from techtrend.deliver.digest import linkify
from techtrend.deliver.slack import SlackClient, to_mrkdwn
from techtrend.platform import queue, telemetry
from techtrend.platform.config import settings, site_blocked
from techtrend.platform.db import session_scope
from techtrend.topic.match import blocked, searchable

# Saturday. `datetime.weekday()` is Monday-0, so Saturday is 5.
REPORT_WEEKDAY = 5
REPORT_HOUR = 15


def tz() -> ZoneInfo:
    """The roundup's clock. Shared with the digest deliberately: two delivery
    surfaces on two different timezones would put the week and the day out of
    step for no reason."""
    return ZoneInfo(settings().digest_timezone)


def week_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """(since, until) for the most recent COMPLETED week.

    `until` is the latest Saturday REPORT_HOUR local that has already passed;
    `since` is seven days before it. Anchoring on a boundary in the past keeps
    the roundup reproducible: running it twice, or re-running it days later
    after an outage, covers the same week rather than a shifted one.
    """
    local = (now or datetime.now(UTC)).astimezone(tz())
    anchor = local.replace(hour=REPORT_HOUR, minute=0, second=0, microsecond=0)
    # Days back to the most recent Saturday, then one more week if that
    # Saturday's hour has not yet arrived.
    back = (local.weekday() - REPORT_WEEKDAY) % 7
    until = anchor - timedelta(days=back)
    if until > local:
        until -= timedelta(days=7)
    return until - timedelta(days=7), until


# Ordered by reach then recency: when the cap bites, the widely-covered stories
# survive into the model's view. description and entities come along so the
# term gate reads the same text the matcher would.
_WEEK = text("""
    SELECT a.title, a.description, a.entities, si.name AS site, si.domain,
           sp.posted_at, sp.ts, st.source_count,
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


def gate(rows: list[Any]) -> tuple[list[Any], int]:
    """Drop every row either content gate rejects. Returns (kept, dropped).

    Runs before the prompt is built, not after the prose comes back: once a
    blocked story is in the model's input it can surface as an unlinked phrase
    in a sentence, and nothing downstream reads the prose.
    """
    s = settings()
    kept: list[Any] = []
    dropped = 0
    for row in rows:
        if ban := site_blocked(row.domain, s.blocked_sites):
            dropped += 1
            telemetry.log.info("weekly.site_blocked", domain=row.domain, ban=ban)
            continue
        story = searchable(row.title, row.description, list(row.entities or []))
        if hit := blocked(story, s.block_terms):
            dropped += 1
            telemetry.log.info("weekly.term_blocked", term=hit)
            continue
        kept.append(row)
    return kept, dropped


def render_headlines(rows: list[Any], until: datetime | None = None) -> str:
    """The model's input: numbered headlines with day, reach and topic.

    The day is included where the digest omits it -- an arc across seven days
    cannot be seen in a list that never says which day a story landed on.

    The week's end date leads the prompt because the forecast half needs it.
    A model with no clock dates its own deadlines from its training cutoff, so
    it will happily file a prediction that "resolves by Q1" two years in the
    past -- which reads as authoritative and is checkable nonsense.
    """
    out = []
    if until is not None:
        local = until.astimezone(tz())
        out.append(f"Week ending {local:%A %d %B %Y}. Today is {local:%d %B %Y}.")
        out.append(
            f"Every date you write must fall AFTER {local:%d %B %Y}."
            " Prefer a relative horizon: 'within three months', 'by mid-next-year'."
        )
        out.append("")
    for i, r in enumerate(rows, 1):
        day = r.posted_at.astimezone(tz()).strftime("%a")
        reach = f", {r.source_count} outlets" if r.source_count > 1 else ""
        topic = f" [{r.topics}]" if r.topics else ""
        out.append(f"{i}. ({day}) {r.title} ({r.site}{reach}){topic}")
    return "\n".join(out)


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


def blocks_for(until: datetime, body: str, n: int, sites: int) -> tuple[str, list[dict[str, Any]]]:
    """(fallback, blocks). Fallback is the push-notification line."""
    local = until.astimezone(tz())
    heading = f"TechTrend Weekly — week ending {local:%d %B %Y}"
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": heading, "emoji": True}}
    ]
    # Slack rejects a section over 3000 chars, so the body is packed into as
    # many sections as it needs rather than truncated.
    for chunk in _chunk(body, 2900):
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"{n} stories · {sites} sources · 7 days to {local:%d %b}",
                }
            ],
        }
    )
    return heading, blocks


async def build(
    sess: Any, channel: str, since: datetime, until: datetime
) -> tuple[str, list[Any], Any]:
    """(prose, rows, totals). Rows come back so the caller resolves permalinks."""
    s = settings()
    args = {"ch": channel, "since": since, "until": until}
    totals = (await sess.execute(_COUNT, args)).one()
    raw = list((await sess.execute(_WEEK, {**args, "cap": s.weekly_max_stories})).all())
    rows, dropped = gate(raw)
    telemetry.log.info(
        "weekly.input", carried=totals.n, considered=len(raw), kept=len(rows), gated=dropped
    )
    if not rows:
        return "", [], totals

    prose = await ai_client().weekly(render_headlines(rows, until))
    # Gating the input is not enough on a surface that WRITES. The model can
    # name a banned subject out of its own knowledge, with no story behind it,
    # and no gate downstream reads prose. A ban that a sentence walks around
    # is not a ban -- so this fails closed and files nothing.
    if hit := blocked(searchable(prose, None, []), settings().block_terms):
        telemetry.log.warning("weekly.output_blocked", term=hit)
        return "", [], totals
    return prose, rows, totals


async def run(job: queue.Job) -> None:
    """The stage entry point: post the week to the channel."""
    s = settings()
    if s.slack_bot_token is None or not s.slack_channel:
        return
    channel = s.slack_channel
    since, until = week_window()

    async with session_scope() as sess:
        body, rows, totals = await build(
            sess, channel, since.astimezone(UTC), until.astimezone(UTC)
        )

    if not body:
        telemetry.log.info("weekly.skipped", reason="no_stories")
        return

    client = SlackClient()
    body = await linkify(to_mrkdwn(body), rows, client, channel)
    fallback, blocks = blocks_for(until, body, totals.n, totals.sites)
    ts = await client.post(channel, fallback, blocks=blocks, unfurl=False)
    telemetry.log.info("weekly.posted", ts=ts, stories=totals.n, chars=len(body))
