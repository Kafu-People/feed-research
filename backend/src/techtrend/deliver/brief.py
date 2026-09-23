"""The brief stage: a watchlist question in, one researched post out.

The second half of the system. `collect` -> `match` reports what publishers
published; this reports what Google's index says people actually posted. They
are different questions and they get different channels, so a brief never
competes with the hourly report for the same attention.

Every gate the other surfaces apply, applies here -- and more carefully, not
less. The hourly report carries publisher headlines we crawled; a brief
carries prose a model wrote about pages we never saw. That is the surface most
likely to put a banned subject in the channel, so the block list is checked on
the model's own words before anything is posted.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import text

from techtrend.ai import gemini
from techtrend.deliver.slack import Block, SlackClient, decode_title, to_slack_report
from techtrend.platform import queue, telemetry
from techtrend.platform.config import settings, site_blocked
from techtrend.platform.db import session_scope
from techtrend.topic.match import blocked, searchable

# The same topic, asked three different questions. The window is what makes a
# daily post news instead of yesterday's overview reprinted -- which is what a
# 17,542-character report becomes when you run it again tomorrow.
CADENCES: dict[str, dict[str, str]] = {
    "daily": {
        "column": "last_run_at",
        "label": "today",
        "window": (
            "Report ONLY what is NEW or CHANGED in the last 24 hours. Do not "
            "restate background a regular reader already knows. If little "
            "happened, say that in one or two sentences rather than padding "
            "with old material. Lead with the newest thing and give its date."
        ),
    },
    "weekly": {
        "column": "last_weekly_at",
        "label": "this week",
        "window": (
            "Cover the last 7 days. What changed, what is new, what moved, and "
            "what it adds up to. Group related items rather than listing them "
            "one by one. Give the date of each item."
        ),
    },
    "monthly": {
        "column": "last_monthly_at",
        "label": "the full picture",
        "window": (
            "Give the complete current overview, the state of things as they "
            "stand now. This is the reference version, so answer the whole "
            "question rather than only what is recent."
        ),
    },
}

_ONE = text("SELECT name, prompt FROM brief_topics WHERE name = :name AND active")


# Built ONCE, from CADENCES, at import. The column name cannot be a bound
# parameter, so the alternative is formatting a string per call -- which reads
# as SQL injection to any reader and to the linter, even though the only
# possible input is a key of a module constant. Building them here makes the
# closed set obvious and leaves no string formatting on the hot path.
_DUE_SQL = {
    name: text(
        f"SELECT name, prompt FROM brief_topics"  # noqa: S608 - column from CADENCES
        f" WHERE active AND ({c['column']} IS NULL OR {c['column']} < :since)"
        f" ORDER BY {c['column']} NULLS FIRST, name"
    )
    for name, c in CADENCES.items()
}
_MARK_SQL = {
    name: text(
        f"UPDATE brief_topics SET {c['column']} = now() WHERE name = :name"  # noqa: S608
    )
    for name, c in CADENCES.items()
}


def configured() -> bool:
    """Both halves or nothing, the same rule the card path uses: a key with no
    channel researches into the void, a channel with no key posts nothing."""
    s = settings()
    return s.gemini_api_key is not None and bool(s.slack_brief_channel)


async def run(job: queue.Job) -> None:
    s = settings()
    if not configured():
        return

    # A one-off question. Not on the watchlist, never repeated, and rendered
    # under the asker's own words rather than a topic name.
    if ask := job.payload.get("ask"):
        await _one(SlackClient(), "question", str(ask), heading=str(ask))
        return

    cadence = str(job.payload.get("cadence") or "daily")
    if cadence not in CADENCES:
        cadence = "daily"

    if name := job.payload.get("name"):
        async with session_scope() as sess:
            rows = list((await sess.execute(_ONE, {"name": str(name)})).all())
    else:
        # Anything whose stamp for THIS cadence is older than its period. A
        # topic can be due weekly and not due daily on the same morning.
        since = datetime.now(UTC) - _period(cadence)
        async with session_scope() as sess:
            rows = list((await sess.execute(_DUE_SQL[cadence], {"since": since})).all())
    if not rows:
        return

    client = SlackClient()
    spent = 0
    for row in rows:
        # The cap is on SEARCHES, not on topics: grounding is billed per query
        # the model decides to run, so one prompt can cost five. Checked before
        # each topic rather than after, because the bill is already incurred by
        # the time a Brief comes back.
        if spent >= s.brief_max_per_day:
            telemetry.log.warning("brief.budget_reached", spent=spent, skipped=row.name)
            break
        spent += await _one(client, row.name, row.prompt, cadence=cadence)
    telemetry.log.info("brief.run_done", cadence=cadence, topics=len(rows), searches=spent)


def _period(cadence: str) -> timedelta:
    """How stale a stamp must be before that cadence is due again.

    Slightly under the nominal period on purpose: a job that fired at 08:00:03
    yesterday must not be judged "not due yet" at 08:00:01 today.
    """
    return {
        "daily": timedelta(hours=20),
        "weekly": timedelta(days=6),
        "monthly": timedelta(days=27),
    }[cadence]


async def _one(
    client: SlackClient,
    name: str,
    prompt: str,
    *,
    heading: str | None = None,
    cadence: str = "daily",
) -> int:
    """Research one topic and post it. Returns searches spent.

    A failure is this topic's failure: the next one still runs, and the
    unmarked `last_run_at` means a transient error retries tomorrow rather
    than silently dropping the beat.
    """
    s = settings()
    # The window goes AFTER the topic's own words, so it is the last thing the
    # model reads and cannot be buried by a long spec like the research one.
    asked = prompt if heading else f"{prompt}\n\n{CADENCES[cadence]['window']}"
    try:
        brief = await gemini.research(asked)
    except gemini.Transient:
        # Not this topic's fault and not today's answer lost: let the queue
        # retry with its own backoff. A 503 during one afternoon used to cost
        # the topic its entire day, because every failure meant "skip".
        telemetry.log.warning("brief.transient", name=name)
        raise
    except gemini.QuotaExceeded:
        # Not retryable and not a rate limit -- it is what a project without
        # billing returns for every grounded call. Hammering it would change
        # nothing, so the whole run stops here.
        telemetry.log.error("brief.quota", name=name)
        raise
    except Exception:  # noqa: BLE001 - one topic, not the watchlist
        telemetry.log.exception("brief.failed", name=name)
        return 0

    if not brief.text.strip():
        telemetry.log.info("brief.empty", name=name, searches=brief.searches)
        return brief.searches

    # THE gate. The model wrote this prose about pages nobody here read, so it
    # is checked before it can reach a channel -- same list, same matcher as
    # the crawled path, no exemption for being generated rather than fetched.
    if hit := blocked(searchable(brief.text, None, []), s.block_terms):
        telemetry.log.warning("brief.blocked", name=name, term=hit)
        return brief.searches

    sources = [src for src in brief.sources if not _banned_source(src)]
    channel = s.slack_brief_channel
    assert channel is not None  # noqa: S101 - narrowed by configured()
    blocks = await _post_both(
        client,
        channel,
        title=heading or name,
        label=None if heading else CADENCES[cadence]["label"],
        brief=brief,
        sources=sources,
    )

    if heading is None:
        async with session_scope() as sess:
            await sess.execute(_MARK_SQL[cadence], {"name": name})
    telemetry.log.info(
        "brief.posted",
        name=name,
        searches=brief.searches,
        sources=len(sources),
        chars=len(brief.text),
        # How many blocks it became: a wall of text is one, a structured
        # report is many. The number that says whether the formatting held.
        blocks=len(blocks),
    )
    return brief.searches


def _banned_source(src: gemini.Source) -> bool:
    """Drop a source from a banned publisher.

    Grounding hands back a redirect URL on Google's own host, not the
    publisher's, so the hostname alone cannot answer this -- the real domain
    is in the title. Both are checked, and the title is the one that usually
    matters.
    """
    banned = settings().blocked_sites
    host = urlsplit(src.uri).netloc
    return bool(site_blocked(host, banned) or site_blocked(src.title.strip(), banned))


def _body_blocks(body: str) -> list[Block]:
    """Section blocks, split at the report's own headings.

    Chunking purely by length puts the break wherever 2,900 characters lands,
    which is usually mid-section and reads as a glitch. Splitting at headings
    first means every visible break is one the report intended, and a divider
    between them turns a wall into a document.
    """
    out: list[Block] = []
    for i, part in enumerate(_sections(body)):
        for j, piece in enumerate(_chunk(part, 2900)):
            # A divider before each new SECTION, never between the pieces of
            # one section that was merely too long for a single block.
            if out and j == 0 and i > 0:
                out.append({"type": "divider"})
            out.append({"type": "section", "text": {"type": "mrkdwn", "text": piece}})
    return out[:45]


def _sections(body: str) -> list[str]:
    """Split on a bold line that stands alone -- what `to_slack_report` turns
    a markdown heading into. Falls back to the whole body when the model wrote
    no headings at all, which is what a short daily answer looks like."""
    parts: list[str] = []
    cur: list[str] = []
    for line in body.split("\n"):
        if _HEADING_LINE.match(line) and cur:
            parts.append("\n".join(cur).strip())
            cur = [line]
        else:
            cur.append(line)
    if cur:
        parts.append("\n".join(cur).strip())
    return [p for p in parts if p]


# A whole line that is bold and nothing else: `*2. Pay by field*`.
_HEADING_LINE = re.compile(r"^\*[^*\n]{1,120}\*\s*$")


def _chunk(body: str, limit: int) -> list[str]:
    """Split a long answer across section blocks, on paragraph boundaries.

    A Slack section caps at 3,000 characters, and this used to truncate at
    2,900 -- fine for a three-paragraph brief, silently destructive for a
    structured report with six headed sections, which is a shape a user can
    ask for in one sentence. Slack allows 50 blocks a message, so splitting
    buys about 145,000 characters before anything has to be dropped.
    """
    if len(body) <= limit:
        return [body]
    parts: list[str] = []
    cur = ""
    for para in body.split("\n\n"):
        # A single paragraph over the limit still has to be cut somewhere.
        while len(para) > limit:
            parts.append(para[:limit])
            para = para[limit:]
        if cur and len(cur) + len(para) + 2 > limit:
            parts.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return _repair_fences(parts)[:44]


def _repair_fences(parts: list[str]) -> list[str]:
    """Re-open and re-close a code fence across a split, tracking state.

    A comparison table can be longer than one 3,000-character block. Split it
    and the first piece opens a fence it never closes, the MIDDLE pieces carry
    no fence at all -- so they render as plain proportional text, which is the
    unreadable thing the code block existed to fix -- and the last piece
    closes a fence nobody opened.

    Counting fences per piece is not enough, because a middle piece has an
    even count of zero and still needs both ends. The state has to be carried.
    """
    out: list[str] = []
    inside = False
    for part in parts:
        opened = inside
        if opened:
            part = "```\n" + part
        # Every fence in the piece, including the one just prepended.
        inside = part.count("```") % 2 == 1
        if inside:
            part = part + "\n```"
        out.append(part)
    return out


def _source_line(sources: list[Any]) -> str:
    """One link per PUBLISHER, not one per citation.

    Grounding titles a source with its domain, and an answer built from forum
    threads cites the same domain over and over: the first brief carried 17
    sources, every one of them titled `reddit.com`. Rendering that literally
    gives a row of twelve identical links, which tells the reader nothing and
    costs a line of the message. One link per domain, with a count when there
    is more than one, says the same thing and is readable.
    """
    first: dict[str, str] = {}
    counts: dict[str, int] = {}
    for src in sources:
        label = decode_title(src.title).replace("|", "❘").replace(">", "&gt;")[:50]
        counts[label] = counts.get(label, 0) + 1
        first.setdefault(label, src.uri)
    parts = []
    for label, uri in list(first.items())[:10]:
        n = counts[label]
        parts.append(f"<{uri}|{label}>" + (f" ×{n}" if n > 1 else ""))
    return " · ".join(parts)


async def _post_both(
    client: SlackClient,
    channel: str,
    *,
    title: str,
    label: str | None,
    brief: gemini.Brief,
    sources: list[Any],
) -> list[Block]:
    """Two posts: the write-up, then the same findings as tables.

    Both, not one. They answer different questions -- understanding wants
    paragraphs, deciding wants a grid -- and one research call produces both
    halves, so the second post is free. Separate messages rather than a
    thread, because a thread hides the tables behind a click and the tables
    are usually what someone came for.
    """
    analysis, tables = brief.parts
    posted: list[Block] = []
    # Sources ride on the LAST post only: repeating a 17-link source line
    # twice says nothing the first one did not.
    halves = [(analysis, label), (tables, "tables")]
    present = [(body, lbl) for body, lbl in halves if body.strip()]
    for i, (body, lbl) in enumerate(present):
        fallback, blocks = _render(
            title,
            body,
            sources if i == len(present) - 1 else [],
            brief.searches,
            label=lbl,
        )
        try:
            # unfurl off: a dozen source links would bury the brief itself.
            await client.post(channel, fallback, blocks=blocks, unfurl=False)
            posted += blocks
        except Exception:  # noqa: BLE001 - one half, never the brief
            telemetry.log.exception("brief.half_failed", half=lbl)
    telemetry.log.info("brief.posted_both", analysis_chars=len(analysis), table_chars=len(tables))
    return posted


def _render(
    name: str, body: str, sources: list[Any], searches: int, *, label: str | None = None
) -> tuple[str, list[Block]]:
    # Slack header blocks are plain_text and cap at 150 characters; a pasted
    # question can be longer than that and would be rejected outright.
    suffix = f" — {label}" if label else ""
    heading = name if len(name) > 40 else f"{name}{suffix}"
    heading = heading[:147] + "…" if len(heading) > 150 else heading
    blocks: list[Block] = [
        {"type": "header", "text": {"type": "plain_text", "text": heading, "emoji": True}},
        *_body_blocks(to_slack_report(body)),
    ]
    if sources:
        blocks.append({"type": "divider"})
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": _source_line(sources)}]}
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"_{searches} searches · {len(sources)} sources_"}
            ],
        }
    )
    return f"{heading} — {body[:160]}", blocks
