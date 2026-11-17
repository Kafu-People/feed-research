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

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import text

from techtrend.ai import gemini
from techtrend.deliver import brief_card
from techtrend.deliver import brief_quality as quality
from techtrend.deliver.slack import Block, SlackClient, decode_title, to_slack_report
from techtrend.platform import queue, telemetry
from techtrend.platform.config import settings, site_blocked
from techtrend.platform.db import session_scope
from techtrend.topic.match import blocked, searchable

# ONE run per topic per day. There used to be three cadences -- daily, weekly
# on Mondays, monthly on the 1st -- each a separate job posting every topic
# again, so on Monday 2026-11-16 the channel got sixteen posts for eight
# topics ten minutes apart. The week now rides inside Monday's daily brief.
CADENCES: dict[str, dict[str, str]] = {
    "daily": {
        "column": "last_run_at",
        "label": "today",
        # The full report, every day: the reader wants the whole picture, and
        # "only the last 24 hours" against a nine-section spec made Claude
        # argue with the spec instead of answering it (2026-11-11).
        "window": (
            "Give the full current report as it stands today. Lead with what "
            "is new or changed most recently and give its date. Date every "
            "data point."
        ),
    },
}
# Added to the daily window on Mondays only.
WEEK_SECTION = (
    "Today is Monday, so also include a section headed THIS WEEK, right after "
    "the opening section, covering the past 7 days: what changed, what is new, "
    "what moved, and what it adds up to, each item with its date."
)
# The guard: a topic that posted less than this long ago is not posted again,
# whatever asked for it -- a restart, a queue retry, a second job, a person.
MIN_GAP_HOURS = 20

_ONE = text("SELECT name, prompt FROM brief_topics WHERE name = :name AND active")
_DUE = text(
    "SELECT name, prompt FROM brief_topics"
    " WHERE active AND (last_run_at IS NULL OR last_run_at < now() - make_interval(hours => :gap))"
    " ORDER BY last_run_at NULLS FIRST, name"
)
# Claim BEFORE researching, atomically. Marking after posting left a window:
# a worker killed between the post and the mark, or a job retried after a
# half-posted brief, posted the same topic twice. The UPDATE ... WHERE is the
# lock: of two runs racing for one topic, exactly one gets a row back.
_CLAIM = text(
    "UPDATE brief_topics SET last_run_at = now()"
    " WHERE name = :name AND active"
    " AND (last_run_at IS NULL OR last_run_at < now() - make_interval(hours => :gap))"
    " RETURNING (SELECT b.last_run_at FROM brief_topics b WHERE b.name = :name)"
)
# A claimed topic that posted nothing gives its day back.
_RELEASE = text("UPDATE brief_topics SET last_run_at = :prev WHERE name = :name")

_UNSET: Any = object()


def configured() -> bool:
    """Both halves or nothing, the same rule the card path uses: a key with no
    channel researches into the void, a channel with no key posts nothing."""
    s = settings()
    return s.gemini_api_key is not None and bool(s.slack_brief_channel)


def client_for_run() -> Any:
    """Slack, or the dry-run file writer when `brief_dry_run_dir` is set."""
    d = settings().brief_dry_run_dir
    return DryRunClient(Path(d)) if d else SlackClient()


async def run(job: queue.Job) -> None:
    s = settings()
    if not configured():
        return

    # A one-off question. Not on the watchlist, never repeated, and rendered
    # under the asker's own words rather than a topic name.
    if ask := job.payload.get("ask"):
        await _one(client_for_run(), "question", str(ask), heading=str(ask), tell=True)
        return

    if name := job.payload.get("name"):
        async with session_scope() as sess:
            rows = list((await sess.execute(_ONE, {"name": str(name)})).all())
    else:
        async with session_scope() as sess:
            rows = list((await sess.execute(_DUE, {"gap": MIN_GAP_HOURS})).all())
    if not rows:
        return

    client = client_for_run()
    spent = 0
    for row in rows:
        # The cap is on SEARCHES, not on topics: search is billed per query
        # the model decides to run, so one prompt can cost eight. Checked
        # before each topic, because the bill is incurred before a Brief
        # comes back.
        if spent >= s.brief_max_per_day:
            telemetry.log.warning("brief.budget_reached", spent=spent, skipped=row.name)
            break
        spent += await _one(client, row.name, row.prompt)
    telemetry.log.info("brief.run_done", topics=len(rows), searches=spent)


def asked_prompt(prompt: str, today: date, *, one_off: bool = False) -> str:
    """The topic's words, today's date, and the daily window.

    The date goes FIRST: without it the model has no "today" and writes
    "637 days ago", or lists a program whose deadline passed last month as
    open. The window goes LAST, so a long spec cannot bury it.
    """
    head = f"Today's date is {today.isoformat()} ({settings().brief_timezone})."
    if one_off:
        return f"{head}\n\n{prompt}"
    window = CADENCES["daily"]["window"]
    if today.weekday() == 0:
        window = f"{window} {WEEK_SECTION}"
    return f"{head}\n\n{prompt}\n\n{window}"


async def _claim(name: str) -> Any:
    """Take today's slot for `name`. Returns the previous stamp, or _UNSET
    when the topic posted within MIN_GAP_HOURS and must not post again."""
    async with session_scope() as sess:
        row = (await sess.execute(_CLAIM, {"name": name, "gap": MIN_GAP_HOURS})).first()
    return _UNSET if row is None else row[0]


async def _release(name: str, prev: Any) -> None:
    async with session_scope() as sess:
        await sess.execute(_RELEASE, {"name": name, "prev": prev})


async def _one(
    client: Any,
    name: str,
    prompt: str,
    *,
    heading: str | None = None,
    tell: bool = False,
) -> int:
    """Research one topic and post it. Returns searches spent.

    A failure is this topic's failure: the next one still runs, and the
    released claim means a transient error retries rather than silently
    dropping the day.

    `tell` is for a one-off question, where silence is the wrong answer. A
    scheduled topic that fails is retried and nobody is waiting on it; a
    person who typed `/techtrend question` IS waiting.
    """
    dry = isinstance(client, DryRunClient)
    scheduled = heading is None and not dry
    prev: Any = None
    if scheduled:
        prev = await _claim(name)
        if prev is _UNSET:
            telemetry.log.info("brief.already_posted", name=name, within_hours=MIN_GAP_HOURS)
            return 0
    posted = False
    try:
        spent, posted = await _research_and_post(client, name, prompt, heading=heading, tell=tell)
        return spent
    finally:
        if scheduled and not posted:
            await _release(name, prev)


async def _research_and_post(
    client: Any, name: str, prompt: str, *, heading: str | None, tell: bool
) -> tuple[int, bool]:
    async def give_up(why: str) -> None:
        if not tell:
            return
        ch = settings().slack_brief_channel
        if not ch:
            return
        try:
            await client.post(ch, f"_{why}_", unfurl=False)
        except Exception:  # noqa: BLE001 - the reason is already logged
            telemetry.log.warning("brief.giveup_failed", name=name)

    s = settings()
    today = quality.today_local()
    asked = asked_prompt(prompt, today, one_off=heading is not None)
    spent = 0
    incomplete = False
    try:
        brief = await gemini.research(asked)
        spent += brief.searches
        # Never ask the reader. One regeneration, then post what there is
        # under an Incomplete label -- or nothing, if it is only a question.
        if quality.asks_reader(brief.text):
            telemetry.log.warning("brief.asked_reader", name=name, attempt=1)
            retry = await gemini.research(asked)
            spent += retry.searches
            brief = retry
            if quality.asks_reader(brief.text):
                telemetry.log.warning("brief.asked_reader", name=name, attempt=2)
                incomplete = True
    except gemini.Transient:
        # Not this topic's fault and not today's answer lost: let the queue
        # retry with its own backoff.
        telemetry.log.warning("brief.transient", name=name)
        raise
    except (gemini.QuotaExceeded, gemini.Depleted) as e:
        # Neither is retryable and neither is a rate limit: stop the run
        # rather than failing eight times.
        telemetry.log.error("brief.billing", name=name, kind=type(e).__name__)
        await give_up(
            "I could not look that up: the research provider's credits are used up. "
            "Top them up and ask again."
        )
        raise
    except Exception:  # noqa: BLE001 - one topic, not the watchlist
        telemetry.log.exception("brief.failed", name=name)
        await give_up("That did not work. It has been logged.")
        return spent, False

    if not brief.text.strip():
        telemetry.log.info("brief.empty", name=name, searches=spent)
        await give_up("I could not find anything on that.")
        return spent, False

    if incomplete and quality.only_question(brief.text):
        telemetry.log.error("brief.question_only", name=name, chars=len(brief.text))
        await give_up("I could not produce a report for that. It has been logged.")
        return spent, False

    # THE gate. The model wrote this prose about pages nobody here read, so it
    # is checked before it can reach a channel -- same list, same matcher as
    # the crawled path, no exemption for being generated rather than fetched.
    if hit := blocked(searchable(brief.text, None, []), s.block_terms):
        telemetry.log.warning("brief.blocked", name=name, term=hit)
        await give_up("I cannot answer that one.")
        return spent, False

    analysis, tables = clean_parts(brief, today, name=name)
    sources = [src for src in brief.sources if not _banned_source(src)]
    channel = s.slack_brief_channel
    assert channel is not None  # noqa: S101 - narrowed by configured()
    if heading is None:
        blocks = await _post_card_and_thread(
            client,
            channel,
            name=name,
            today=today,
            analysis=analysis,
            tables=tables,
            searches=spent,
            sources=sources,
            incomplete=incomplete,
        )
    else:  # a one-off question: short already, nothing to scroll past
        blocks = await _post_both(
            client,
            channel,
            title=heading,
            label=None,
            analysis=analysis,
            tables=tables,
            searches=spent,
            sources=sources,
            incomplete=incomplete,
        )
    telemetry.log.info(
        "brief.posted",
        name=name,
        searches=spent,
        sources=len(sources),
        chars=len(brief.text),
        # How many blocks it became: a wall of text is one, a structured
        # report is many. The number that says whether the formatting held.
        blocks=len(blocks),
        incomplete=incomplete,
    )
    return spent, bool(blocks)


def clean_parts(brief: gemini.Brief, today: date, *, name: str = "") -> tuple[str, str]:
    """Both halves with relative dates made absolute and expired items gone."""
    out = []
    for part in brief.parts:
        part, n = quality.absolutize_relative_dates(part, today)
        part, removed = quality.drop_expired(part, today)
        if n:
            telemetry.log.info("brief.dates_absolutized", name=name, count=n)
        for item in removed:
            telemetry.log.info("brief.expired_removed", name=name, item=item[:300])
        out.append(part)
    return out[0], out[1]


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


# Slack caps a section's text at 3,000 characters and counts it AFTER its own
# escaping (& -> &amp;): the Nov 16 redteam table went out at 2,904 characters
# and was stored at 3,126, and Slack then showed nothing but the fallback line.
SECTION_LIMIT = 2500
# Blocks per message is 50; leave room for header, divider and two footers.
BODY_BLOCKS_PER_MESSAGE = 44


def slack_len(s: str) -> int:
    """Length as Slack stores it: & < > become entities, except inside links."""
    bare = re.sub(r"<(https?://|mailto:)[^>|]+(\|[^>]*)?>", lambda m: m[0][1:-1], s)
    return len(s) + 4 * bare.count("&") + 3 * bare.count("<") + 3 * bare.count(">")


def _body_blocks(body: str) -> list[Block]:
    """Section blocks, split at the report's own headings. Never truncated.

    Splitting at headings first means every visible break is one the report
    intended, and a divider between them turns a wall into a document.
    """
    out: list[Block] = []
    for i, part in enumerate(_sections(body)):
        for j, piece in enumerate(_chunk(part, SECTION_LIMIT)):
            # A divider before each new SECTION, never between the pieces of
            # one section that was merely too long for a single block.
            if out and j == 0 and i > 0:
                out.append({"type": "divider"})
            out.append({"type": "section", "text": {"type": "mrkdwn", "text": piece}})
    return out


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
    """Split a long answer into pieces that each fit one section block.

    In order, always. The old version cut an oversized paragraph and appended
    the pieces BEFORE flushing the text it was holding, so on 2026-11-16 a
    table's heading landed after the table. An oversized paragraph is now
    split on line boundaries (a table is one paragraph of many lines), and a
    single line is only ever cut when it alone is over the limit.

    The limit leaves room for the fence a split code block gains on each side.
    """
    room = limit - 10
    if slack_len(body) <= room:
        return [body]
    parts: list[str] = []
    cur = ""

    def add(piece: str, sep: str) -> None:
        nonlocal cur
        if cur and slack_len(cur) + slack_len(piece) + len(sep) > room:
            parts.append(cur)
            cur = piece
        else:
            cur = f"{cur}{sep}{piece}" if cur else piece

    for para in body.split("\n\n"):
        if slack_len(para) <= room:
            add(para, "\n\n")
            continue
        for line in para.split("\n"):
            while slack_len(line) > room:
                cut = room // 2
                add(line[:cut], "\n")
                line = line[cut:]
            add(line, "\n")
    if cur:
        parts.append(cur)
    return _repair_fences(parts)


def _repair_fences(parts: list[str]) -> list[str]:
    """Re-open and re-close a code fence across a split, tracking state.

    Split a table and the first piece opens a fence it never closes, the
    MIDDLE pieces carry no fence at all -- so they render as proportional
    text -- and the last piece closes a fence nobody opened. Counting fences
    per piece is not enough: the state has to be carried.
    """
    out: list[str] = []
    inside = False
    for part in parts:
        if inside:
            part = "```\n" + part
        # Every fence in the piece, including the one just prepended.
        inside = part.count("```") % 2 == 1
        if inside:
            part = part + "\n```"
        out.append(part)
    return out


def _source_line(sources: list[Any]) -> str:
    """One link per PUBLISHER, not one per citation.

    An answer built from forum threads cites the same domain over and over.
    One link per domain, with a count when there is more than one, says the
    same thing and is readable.
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


UNVERIFIED = "*UNVERIFIED (no sources)*"
INCOMPLETE = "*Incomplete* — this report could not be completed in full."


async def _post_both(
    client: Any,
    channel: str,
    *,
    title: str,
    label: str | None,
    analysis: str,
    tables: str,
    searches: int,
    sources: list[Any],
    incomplete: bool = False,
    thread_ts: str | None = None,
) -> list[Block]:
    """The write-up, then the same findings as tables -- one of each, at most.

    Top-level for a one-off question; as replies under the channel card
    (`thread_ts`) for a scheduled brief.

    Separate messages rather than a thread, because a thread hides the tables
    behind a click and the tables are usually what someone came for. Either
    half may become numbered parts (1/2, 2/2) when it is longer than one Slack
    message holds; nothing is cut.

    Every footer gives the REAL source count. The links ride on the last post
    only, but the count used to as well, so every write-up said "8 searches ·
    0 sources" while the log said 65.
    """
    flags = _flags(sources, incomplete)
    if flags and analysis.strip():
        analysis = "\n".join(flags) + "\n\n" + analysis
    elif flags:
        tables = "\n".join(flags) + "\n\n" + tables

    posted: list[Block] = []
    halves = [(analysis, label), (tables, "tables")]
    present = [(body, lbl) for body, lbl in halves if body.strip()]
    for i, (body, lbl) in enumerate(present):
        messages = _render_parts(
            title,
            body,
            sources if i == len(present) - 1 else [],
            searches,
            label=lbl,
            source_count=len(sources),
        )
        for fallback, blocks in messages:
            try:
                # unfurl off: a dozen source links would bury the brief itself.
                await client.post(
                    channel, fallback, blocks=blocks, thread_ts=thread_ts, unfurl=False
                )
                posted += blocks
            except Exception:  # noqa: BLE001 - one part, never the brief
                telemetry.log.exception("brief.half_failed", half=lbl)
    telemetry.log.info("brief.posted_both", analysis_chars=len(analysis), table_chars=len(tables))
    return posted


def _flags(sources: list[Any], incomplete: bool) -> list[str]:
    out = []
    if not sources:
        out.append(UNVERIFIED)
    if incomplete:
        out.append(INCOMPLETE)
    return out


async def _post_card_and_thread(
    client: Any,
    channel: str,
    *,
    name: str,
    today: date,
    analysis: str,
    tables: str,
    searches: int,
    sources: list[Any],
    incomplete: bool = False,
) -> list[Block]:
    """A short card in the channel; the full report and tables in its thread.

    Eight briefs a day posted top-level were a wall of 15,000-40,000-character
    reports. The card is what the channel reads; the thread is for whoever
    wants the detail, and it is where follow-up questions go (discuss.py reads
    the whole thread, report included).

    If the card cannot be posted, the brief goes out the old way -- two
    top-level posts -- rather than not at all.
    """
    card = await brief_card.summarize(f"{analysis}\n\n{tables}", today, name=name)
    text_, blocks = brief_card.card_blocks(
        card,
        title=name,
        today=today,
        searches=searches,
        source_count=len(sources),
        flags=_flags(sources, incomplete),
    )
    try:
        ts = await client.post(channel, text_, blocks=blocks, unfurl=False)
    except Exception:  # noqa: BLE001 - the report still goes out, top-level
        telemetry.log.exception("brief.card_post_failed", name=name)
        return await _post_both(
            client,
            channel,
            title=name,
            label=CADENCES["daily"]["label"],
            analysis=analysis,
            tables=tables,
            searches=searches,
            sources=sources,
            incomplete=incomplete,
        )
    telemetry.log.info("brief.card_posted", name=name, generated=card.generated)
    thread = await _post_both(
        client,
        channel,
        title=name,
        label="full report",
        analysis=analysis,
        tables=tables,
        searches=searches,
        sources=sources,
        incomplete=incomplete,
        thread_ts=str(ts),
    )
    return blocks + thread


def _render_parts(
    name: str,
    body: str,
    sources: list[Any],
    searches: int,
    *,
    label: str | None = None,
    source_count: int | None = None,
) -> list[tuple[str, list[Block]]]:
    """One half as one or more Slack messages, numbered when more than one."""
    # Slack header blocks are plain_text and cap at 150 characters; a pasted
    # question can be longer than that and would be rejected outright.
    suffix = f" — {label}" if label else ""
    base = name if len(name) > 40 else f"{name}{suffix}"
    # The model's own `---` rules go: dividers already separate the sections,
    # and both together showed as two rules in a row (2026-11-17 dry run).
    body = re.sub(r"^[ \t]*-{3,}[ \t]*$\n?", "", body, flags=re.M)
    body_blocks = _body_blocks(to_slack_report(body))
    groups = [
        body_blocks[i : i + BODY_BLOCKS_PER_MESSAGE]
        for i in range(0, max(1, len(body_blocks)), BODY_BLOCKS_PER_MESSAGE)
    ] or [[]]
    # A group must not start with a divider: it was the break between two
    # sections that now fall in different messages.
    groups = [g[1:] if g and g[0]["type"] == "divider" else g for g in groups]
    count = len(sources) if source_count is None else source_count
    out: list[tuple[str, list[Block]]] = []
    for n, group in enumerate(groups, start=1):
        heading = f"{base} ({n}/{len(groups)})" if len(groups) > 1 else base
        heading = heading[:147] + "…" if len(heading) > 150 else heading
        blocks: list[Block] = [
            {"type": "header", "text": {"type": "plain_text", "text": heading, "emoji": True}},
            *group,
        ]
        if n == len(groups):
            if sources:
                blocks.append({"type": "divider"})
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": _source_line(sources)}],
                    }
                )
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"_{searches} searches · {count} sources_"}
                    ],
                }
            )
        out.append((f"{heading} — {_plain(body)[:160]}", blocks))
    return out


def _plain(body: str) -> str:
    """The notification line: no markdown pipes or fences, one line."""
    t = re.sub(r"^\s*\|.*\|\s*$", "", body, flags=re.M)
    t = re.sub(r"[#*`|]+", "", t)
    return " ".join(t.split())


def _render(
    name: str, body: str, sources: list[Any], searches: int, *, label: str | None = None
) -> tuple[str, list[Block]]:
    """A half that fits one message (the common case), as (fallback, blocks)."""
    fallback, blocks = _render_parts(name, body, sources, searches, label=label)[0]
    return fallback, blocks


def slack_problems(blocks: list[Block]) -> list[str]:
    """What Slack would reject or fail to show in one message's blocks."""
    out = []
    if len(blocks) > 50:
        out.append(f"{len(blocks)} blocks (max 50)")
    for i, b in enumerate(blocks):
        t = b.get("text") or {}
        s = t.get("text", "") if isinstance(t, dict) else ""
        if b["type"] == "section" and slack_len(s) > 3000:
            out.append(f"block {i}: section {slack_len(s)} chars (max 3000)")
        if b["type"] == "section" and not s.strip():
            out.append(f"block {i}: empty section")
        if b["type"] == "header" and len(s) > 150:
            out.append(f"block {i}: header {len(s)} chars (max 150)")
        if b["type"] == "section" and re.search(r"^\s*\|.*\|\s*$", s, re.M) and "```" not in s:
            out.append(f"block {i}: raw markdown table outside a code block")
    return out


class DryRunClient:
    """Stands in for SlackClient: writes each post to a file, posts nothing."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.posts: list[dict[str, Any]] = []

    async def post(
        self,
        channel: str,
        text_: str,
        blocks: list[Block] | None = None,
        thread_ts: str | None = None,
        **kw: Any,
    ) -> str:
        """Same contract as SlackClient.post: returns the message's ts."""
        n = len(self.posts) + 1
        ts = f"dry.{n}"
        problems = slack_problems(blocks or [])
        rec = {
            "n": n,
            "ts": ts,
            "thread_ts": thread_ts,
            "channel": channel,
            "text": text_,
            "blocks": blocks or [],
            "problems": problems,
        }
        self.posts.append(rec)
        where = "thread" if thread_ts else "channel"
        # Made again per post: on 2026-11-17 a directory created at the start
        # of a ten-minute run was gone when its first post was written.
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{n:02d}-{where}"
        path.with_suffix(".json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        path.with_suffix(".md").write_text(_as_markdown(rec), encoding="utf-8")
        telemetry.log.info("brief.dry_run_post", file=str(path), problems=problems)
        return ts


def _as_markdown(rec: dict[str, Any]) -> str:
    """Roughly what a reader sees: header, sections, footers, problems."""
    lines = []
    for b in rec["blocks"]:
        if b["type"] == "header":
            lines.append(f"# {b['text']['text']}")
        elif b["type"] == "section":
            lines.append(b["text"]["text"])
        elif b["type"] == "divider":
            lines.append("---")
        elif b["type"] == "context":
            lines.append(" ".join(e.get("text", "") for e in b.get("elements", [])))
    if rec["problems"]:
        lines.append("\n**SLACK PROBLEMS:** " + "; ".join(rec["problems"]))
    return "\n\n".join(lines) + "\n"
