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

from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import text

from techtrend.ai import gemini
from techtrend.deliver.slack import SlackClient, decode_title, to_mrkdwn
from techtrend.platform import queue, telemetry
from techtrend.platform.config import settings, site_blocked
from techtrend.platform.db import session_scope
from techtrend.topic.match import blocked, searchable

_DUE = text("""
    SELECT name, prompt FROM brief_topics
     WHERE active
       AND (last_run_at IS NULL OR last_run_at < :since)
     ORDER BY last_run_at NULLS FIRST, name
""")
_ONE = text("SELECT name, prompt FROM brief_topics WHERE name = :name AND active")
_MARK = text("UPDATE brief_topics SET last_run_at = now() WHERE name = :name")


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

    if name := job.payload.get("name"):
        async with session_scope() as sess:
            rows = list((await sess.execute(_ONE, {"name": str(name)})).all())
    else:
        # Anything not researched since the start of today's local day.
        from techtrend.deliver.digest import local_day, tz

        since = datetime.combine(local_day(), datetime.min.time(), tzinfo=tz()).astimezone(UTC)
        async with session_scope() as sess:
            rows = list((await sess.execute(_DUE, {"since": since})).all())
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
        spent += await _one(client, row.name, row.prompt)
    telemetry.log.info("brief.run_done", topics=len(rows), searches=spent)


async def _one(client: SlackClient, name: str, prompt: str, *, heading: str | None = None) -> int:
    """Research one topic and post it. Returns searches spent.

    A failure is this topic's failure: the next one still runs, and the
    unmarked `last_run_at` means a transient error retries tomorrow rather
    than silently dropping the beat.
    """
    s = settings()
    try:
        brief = await gemini.research(prompt)
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
    fallback, blocks = _render(heading or name, brief.text, sources, brief.searches)
    # unfurl off: a source list of a dozen links would bury the brief itself.
    await client.post(channel, fallback, blocks=blocks, unfurl=False)

    if heading is None:
        async with session_scope() as sess:
            await sess.execute(_MARK, {"name": name})
    telemetry.log.info(
        "brief.posted",
        name=name,
        searches=brief.searches,
        sources=len(sources),
        chars=len(brief.text),
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


def _source_line(sources: list) -> str:
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


def _render(name: str, body: str, sources: list, searches: int) -> tuple[str, list[dict]]:
    # Slack header blocks are plain_text and cap at 150 characters; a pasted
    # question can be longer than that and would be rejected outright.
    heading = name if len(name) > 40 else f"Brief — {name}"
    heading = heading[:147] + "…" if len(heading) > 150 else heading
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": heading, "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": to_mrkdwn(body)[:2900]}},
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
