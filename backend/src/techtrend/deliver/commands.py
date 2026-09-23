"""`/techtrend` -- the user-facing controls for the brief list.

One namespaced command with subcommands, not `/add` and `/remove`. Bare verbs
collide with whatever else is installed in the workspace and Slack resolves a
collision by its own rules, not ours; `/techtrend` is ours alone and appears in
the autocomplete with its own help.

Replies go back through Slack's `response_url`, which is ephemeral by default:
managing a watchlist is a conversation between one person and the bot, and the
channel does not need a copy of every `list`. The brief itself is the part
everyone sees.

Slash commands arrive over the SAME Socket Mode connection as mentions, so
none of this needs a public HTTPS endpoint.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from sqlalchemy import text

from techtrend.platform import telemetry
from techtrend.platform.config import settings
from techtrend.platform.db import session_scope


def _blocks(*, title: str, body: str, note: str | None = None) -> list[dict]:
    """One shape for every reply: a bold title, the body, a quiet note.

    Slash-command replies used to be a single run of text with markdown in it.
    In Slack that renders as a wall -- no spacing, no hierarchy, the important
    line no louder than the example under it. Block Kit is what gives a reply
    a shape, and `context` is what makes a hint read as a hint.
    """
    out: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\n{body}"}}
    ]
    if note:
        out.append({"type": "context", "elements": [{"type": "mrkdwn", "text": note}]})
    return out


HELP_BLOCKS = [
    {
        "type": "header",
        "text": {"type": "plain_text", "text": "TechTrend briefs", "emoji": True},
    },
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "A watchlist researched every day with Google Search. "
                "It reads forums and discussion, not press releases."
            ),
        },
    },
    {"type": "divider"},
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "*`/techtrend list`*\nSee what is being watched\n\n"
                "*`/techtrend add <name> <prompt>`*\nStart watching something. "
                "The name is one word.\n\n"
                "*`/techtrend edit <name> <new prompt>`*\nChange what it asks\n\n"
                "*`/techtrend remove <name>`*\nStop watching it\n\n"
                "*`/techtrend run <name>`*\nResearch it now\n\n"
                "*`/techtrend question <your question>`*\nAsk once. Nothing is saved."
            ),
        },
    },
    {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    "_Example:_ `/techtrend add mercor What are people saying this week "
                    "about Mercor pay rates?`"
                ),
            }
        ],
    },
]

HELP = (
    "*TechTrend briefs* — a watchlist researched daily with Google Search.\n\n"
    "`/techtrend list` — what is being watched\n"
    "`/techtrend add <name> <prompt>` — start watching something\n"
    "`/techtrend remove <name>` — stop watching it\n"
    "`/techtrend run <name>` — research it now, without waiting for tomorrow\n\n"
    "_Example:_ `/techtrend add dataannotation What are people saying this week "
    "about DataAnnotation and Mercor pay rates?`"
)

# A name is one word: it is the handle used by `remove` and `run`, so a
# multi-word name would make "which part was the name" ambiguous against the
# prompt that follows it.
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,38}$")

_LIST = text("""
    SELECT name, prompt, added_by, last_run_at
      FROM brief_topics WHERE active ORDER BY name
""")
_ADD = text("""
    INSERT INTO brief_topics (name, prompt, added_by, active)
    VALUES (:name, :prompt, :by, true)
    ON CONFLICT (name) DO UPDATE
       SET prompt = EXCLUDED.prompt, added_by = EXCLUDED.added_by, active = true
    RETURNING (xmax = 0) AS created
""")
_REMOVE = text("UPDATE brief_topics SET active = false WHERE name = :name AND active RETURNING id")
_EDIT = text("UPDATE brief_topics SET prompt = :prompt WHERE name = :name AND active")
_GET = text("SELECT name, prompt FROM brief_topics WHERE name = :name AND active")
# Questions asked today, counted off the queue itself so no new table is
# needed. `purge_done` keeps the jobs table short, which is fine: it purges
# rows far older than one day.
_ASKED_TODAY = text("""
    SELECT count(*) FROM jobs
     WHERE stage = 'brief' AND key LIKE 'brief:ask:%' AND created_at > now() - interval '1 day'
""")


def _wrong_channel(payload: dict[str, Any]) -> str | None:
    """The command's home channel, if it was run somewhere else.

    Slack offers a slash command in EVERY channel the moment it exists, so
    without this `/techtrend list` works in #techtrend-ai, in a DM, and in
    any unrelated channel someone happens to be in. The watchlist belongs to
    one channel -- the one its briefs post to -- and the command should say so
    rather than quietly working everywhere.

    Matched on name, because that is what the operator configures; Slack sends
    both the id and the name with every command.
    """
    home = (settings().slack_brief_channel or "").lstrip("#").strip()
    if not home:
        return None  # unconfigured: refusing everywhere would be worse
    here = str(payload.get("channel_name") or "").lstrip("#").strip()
    # A DM reports as `directmessage`, which is never the home channel.
    return None if here == home else home


async def handle(payload: dict[str, Any]) -> None:
    """Route one slash command. Never raises: a bad command is a reply."""
    args = str(payload.get("text") or "").strip()
    user = payload.get("user_id")
    response_url = str(payload.get("response_url") or "")

    if home := _wrong_channel(payload):
        telemetry.log.info("command.wrong_channel", channel=payload.get("channel_name"))
        await _respond(
            response_url,
            f"Use /techtrend in #{home}",
            _blocks(
                title=f"`/techtrend` lives in #{home}",
                body="Join that channel and run it there.",
            ),
        )
        return
    verb, _, rest = args.partition(" ")
    verb, rest = verb.strip().lower(), rest.strip()

    try:
        if verb in ("", "help"):
            reply = ("TechTrend briefs", HELP_BLOCKS)
        elif verb == "list":
            reply = await _do_list()
        elif verb == "add":
            reply = await _do_add(rest, user)
        elif verb == "edit":
            reply = await _do_edit(rest)
        elif verb in ("remove", "rm", "delete"):
            reply = await _do_remove(rest)
        elif verb == "run":
            reply = await _do_run(rest)
        elif verb in ("question", "ask", "q"):
            reply = await _do_question(rest, user)
        else:
            reply = (
                f"Unknown command: {verb}",
                _blocks(
                    title=f"I do not know `{verb}`",
                    body="Here is everything `/techtrend` can do.",
                )
                + HELP_BLOCKS[2:],
            )
    except Exception:  # noqa: BLE001 - a broken command must not kill the listener
        telemetry.log.exception("command.failed", verb=verb)
        reply = (
            "Something went wrong",
            _blocks(
                title="Something went wrong",
                body="That did not work. The error is in the log.",
            ),
        )

    await _respond(response_url, *reply)


async def _do_question(rest: str, user: str | None) -> tuple[str, list[dict]]:
    """Research one question now, and save nothing.

    Rate-limited against the `jobs` table rather than a new counter: a
    grounded question costs 4 to 8 searches, the operator's budget is small,
    and a question is the one entry point a person can fire repeatedly by
    hand. The daily cap covers the scheduled run only -- this covers this.
    """
    from techtrend.platform import queue

    question = rest.strip()
    if len(question) < 12:
        return (
            "Ask a longer question",
            _blocks(
                title="That question is too short",
                body="Ask it as a full question, the way you would ask a person.",
                note=(
                    "_Example:_ `/techtrend question Is Mercor still paying "
                    "$90/hr for law experts?`"
                ),
            ),
        )
    async with session_scope() as s:
        used = (await s.execute(_ASKED_TODAY)).scalar_one()
    if used >= settings().brief_questions_per_day:
        return (
            "Daily question limit reached",
            _blocks(
                title="That is enough questions for today",
                body=(
                    f"{used} asked already. Each one runs several Google searches "
                    "and they are billed per search."
                ),
                note="_The limit resets at midnight. The watchlist still runs as normal._",
            ),
        )
    await queue.enqueue("brief", f"brief:ask:{_bucket()}:{user}", {"ask": question}, priority=50)
    telemetry.log.info("command.question", user=user, chars=len(question))
    return (
        "Researching your question",
        _blocks(
            title="Researching now",
            body=f"> {question}",
            note=f"_The answer posts to this channel in a minute. {used + 1} of "
            f"{settings().brief_questions_per_day} questions used today._",
        ),
    )


async def _do_list() -> tuple[str, list[dict]]:
    async with session_scope() as s:
        rows = (await s.execute(_LIST)).all()
    if not rows:
        return (
            "Nothing on the watchlist",
            _blocks(
                title="Nothing on the watchlist yet",
                body="Add the first one and it will be researched tomorrow morning.",
                note="_Example:_ `/techtrend add mercor What are people saying about Mercor pay?`",
            ),
        )
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Watchlist — {len(rows)} topic{'s' if len(rows) > 1 else ''}",
                "emoji": True,
            },
        }
    ]
    for r in rows:
        when = r.last_run_at.strftime("%d %b, %H:%M") if r.last_run_at else "not run yet"
        who = f" · <@{r.added_by}>" if r.added_by else ""
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{r.name}*\n> {r.prompt[:280]}"},
            }
        )
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{when}_{who}"}]}
        )
    return (f"{len(rows)} topics on the watchlist", blocks)


async def _do_add(rest: str, user: str | None) -> tuple[str, list[dict]]:
    name, _, prompt = rest.partition(" ")
    name, prompt = name.strip().lower(), prompt.strip()
    note: str | None = None
    if not name or not prompt:
        return (
            "Needs a name and a prompt",
            _blocks(
                title="That needs a name and a prompt",
                body="`/techtrend add <name> <prompt>` — the name is one word.",
                note="_Example:_ `/techtrend add mercor What are people saying about Mercor pay?`",
            ),
        )
    if not _NAME.match(name):
        return (
            "Bad name",
            _blocks(
                title=f"`{name}` will not work as a name",
                body="Use one word: letters, digits, `-` and `_`. Up to 39 characters.",
            ),
        )
    if len(prompt) < 15:
        return (
            "Prompt too short",
            _blocks(
                title="That prompt is too short to research",
                body="Ask it as a full question, the way you would ask a person.",
            ),
        )
    async with session_scope() as s:
        created = (await s.execute(_ADD, {"name": name, "prompt": prompt, "by": user})).scalar_one()
    verb = "Now watching" if created else "Updated"
    telemetry.log.info("command.add", name=name, created=bool(created), user=user)
    note = "_First brief arrives with tomorrow's run. `/techtrend run " + name + "` does it now._"
    # `add Data Annotation What are people...` reads as a two-word name to a
    # human and parses as name=`data`, prompt=`Annotation What are people...`.
    # The confirmation already shows what was parsed, but nobody reads a
    # confirmation that looks like success -- so say it outright when the
    # prompt begins mid-phrase.
    if prompt[:1].isupper() and prompt.split(" ", 1)[0].isalpha() and len(prompt.split()) > 1:
        note = (
            f"_The name is the first word only — `{name}`. If you meant a longer name, "
            f"`/techtrend remove {name}` and add it again as one word._"
        )
    return (
        f"{verb} {name}",
        _blocks(title=f"{verb} `{name}`", body=f"> {prompt}", note=note),
    )


async def _do_edit(rest: str) -> tuple[str, list[dict]]:
    """Replace the prompt on a topic that already exists.

    Distinct from `add`, which upserts. `add` on a name that exists quietly
    rewrites it, so someone who mistypes a name there creates a SECOND topic
    instead of fixing the first. `edit` refuses a name it does not know, which
    is the whole reason to have it: the name is unique, so "change this one"
    is always answerable.
    """
    name, _, prompt = rest.partition(" ")
    name, prompt = name.strip().lower(), prompt.strip()
    if not name or not prompt:
        return (
            "Needs a name and a new prompt",
            _blocks(
                title="That needs a name and a new prompt",
                body="`/techtrend edit <name> <new prompt>`",
                note="_`/techtrend list` shows the names._",
            ),
        )
    if len(prompt) < 15:
        return (
            "Prompt too short",
            _blocks(
                title="That prompt is too short to research",
                body="Ask it as a full question, the way you would ask a person.",
            ),
        )
    async with session_scope() as s:
        old = (await s.execute(_GET, {"name": name})).one_or_none()
        if old is None:
            return (
                f"{name} is not on the watchlist",
                _blocks(
                    title=f"`{name}` is not on the watchlist",
                    body="`/techtrend list` shows what is. `/techtrend add` makes a new one.",
                ),
            )
        await s.execute(_EDIT, {"name": name, "prompt": prompt})
    telemetry.log.info("command.edit", name=name)
    return (
        f"Updated {name}",
        _blocks(
            title=f"Updated `{name}`",
            body=f"*Now:*\n> {prompt}\n\n*Was:*\n> {old.prompt[:240]}",
            note=f"_Takes effect on the next run. `/techtrend run {name}` uses it now._",
        ),
    )


async def _do_remove(rest: str) -> tuple[str, list[dict]]:
    name = rest.strip().lower()
    if not name:
        return ("Which one?", _blocks(title="Which one?", body="`/techtrend remove <name>`"))
    async with session_scope() as s:
        gone = (await s.execute(_REMOVE, {"name": name})).scalar_one_or_none()
    if gone is None:
        return (
            f"{name} is not on the watchlist",
            _blocks(
                title=f"`{name}` is not on the watchlist",
                body="`/techtrend list` shows what is.",
            ),
        )
    telemetry.log.info("command.remove", name=name)
    return (
        f"Stopped watching {name}",
        _blocks(
            title=f"Stopped watching `{name}`",
            body="It will not be researched again.",
            note="_Adding it again brings back the same prompt._",
        ),
    )


async def _do_run(rest: str) -> tuple[str, list[dict]]:
    """Queue one brief now. The work is a job, not this handler: Slack wants
    an ack in 3 seconds and a grounded search takes far longer."""
    from techtrend.platform import queue

    name = rest.strip().lower()
    if not name:
        return ("Which one?", _blocks(title="Which one?", body="`/techtrend run <name>`"))
    async with session_scope() as s:
        row = (await s.execute(_GET, {"name": name})).one_or_none()
    if row is None:
        return (
            f"{name} is not on the watchlist",
            _blocks(
                title=f"`{name}` is not on the watchlist",
                body="`/techtrend list` shows what is.",
            ),
        )
    await queue.enqueue("brief", f"brief:manual:{name}:{_bucket()}", {"name": name}, priority=50)
    return (
        f"Researching {name}",
        _blocks(
            title=f"Researching `{name}` now",
            body="> " + row.prompt[:280],
            note="_The brief posts to this channel in a minute._",
        ),
    )


def _bucket() -> int:
    """A minute bucket, so a double-click is one job and not two."""
    import time

    return int(time.time() // 60)


async def _respond(response_url: str, text_: str, blocks: list[dict] | None = None) -> None:
    """Reply ephemerally via the response_url Slack hands us.

    No scope needed and only the invoker sees it, which is what a watchlist
    edit should be. A failure here is logged and dropped: the command already
    did its work, and the listener must stay up.
    """
    if not response_url:
        return
    try:
        async with httpx.AsyncClient(timeout=settings().slack_timeout_s) as c:
            body = {"response_type": "ephemeral", "text": text_}
            if blocks:
                body["blocks"] = blocks
            await c.post(response_url, json=body)
    except Exception:  # noqa: BLE001 - the reply, not the command
        telemetry.log.exception("command.reply_failed")
