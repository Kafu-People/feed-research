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
_GET = text("SELECT name, prompt FROM brief_topics WHERE name = :name AND active")


async def handle(payload: dict[str, Any]) -> None:
    """Route one slash command. Never raises: a bad command is a reply."""
    args = str(payload.get("text") or "").strip()
    user = payload.get("user_id")
    response_url = str(payload.get("response_url") or "")
    verb, _, rest = args.partition(" ")
    verb, rest = verb.strip().lower(), rest.strip()

    try:
        if verb in ("", "help"):
            reply = HELP
        elif verb == "list":
            reply = await _do_list()
        elif verb == "add":
            reply = await _do_add(rest, user)
        elif verb in ("remove", "rm", "delete"):
            reply = await _do_remove(rest)
        elif verb == "run":
            reply = await _do_run(rest)
        else:
            reply = f"Unknown subcommand `{verb}`.\n\n{HELP}"
    except Exception:  # noqa: BLE001 - a broken command must not kill the listener
        telemetry.log.exception("command.failed", verb=verb)
        reply = "Something went wrong running that. It has been logged."

    await _respond(response_url, reply)


async def _do_list() -> str:
    async with session_scope() as s:
        rows = (await s.execute(_LIST)).all()
    if not rows:
        return "Nothing on the watchlist yet.\n\n" + HELP
    lines = [f"*{len(rows)} on the watchlist*"]
    for r in rows:
        when = r.last_run_at.strftime("%d %b %H:%M") if r.last_run_at else "never run"
        who = f" · added by <@{r.added_by}>" if r.added_by else ""
        lines.append(f"\n*{r.name}* — _{when}_{who}\n> {r.prompt[:300]}")
    return "\n".join(lines)


async def _do_add(rest: str, user: str | None) -> str:
    name, _, prompt = rest.partition(" ")
    name, prompt = name.strip().lower(), prompt.strip()
    if not name or not prompt:
        return "Needs a name and a prompt: `/techtrend add <name> <prompt>`\n\n" + HELP
    if not _NAME.match(name):
        return f"`{name}` is not a usable name — letters, digits, `-` and `_`, max 39 characters."
    if len(prompt) < 15:
        return "That prompt is too short to research. Ask it as a question."
    async with session_scope() as s:
        created = (await s.execute(_ADD, {"name": name, "prompt": prompt, "by": user})).scalar_one()
    verb = "Now watching" if created else "Updated"
    telemetry.log.info("command.add", name=name, created=bool(created), user=user)
    out = f"{verb} *{name}*.\n> {prompt}\n\nFirst brief lands with tomorrow's run."
    # `add Data Annotation What are people...` reads as a two-word name to a
    # human and parses as name=`data`, prompt=`Annotation What are people...`.
    # The confirmation already shows what was parsed, but nobody reads a
    # confirmation that looks like success -- so say it outright when the
    # prompt begins mid-phrase.
    if prompt[:1].isupper() and prompt.split(" ", 1)[0].isalpha() and len(prompt.split()) > 1:
        out += (
            f"\n\n_The name is the first word only — `{name}`. If you meant a longer name, "
            f"`/techtrend remove {name}` and add it as one word._"
        )
    return out


async def _do_remove(rest: str) -> str:
    name = rest.strip().lower()
    if not name:
        return "Which one? `/techtrend remove <name>`"
    async with session_scope() as s:
        gone = (await s.execute(_REMOVE, {"name": name})).scalar_one_or_none()
    if gone is None:
        return f"`{name}` is not on the watchlist. `/techtrend list` shows what is."
    telemetry.log.info("command.remove", name=name)
    return f"Stopped watching *{name}*. Adding it again restores it."


async def _do_run(rest: str) -> str:
    """Queue one brief now. The work is a job, not this handler: Slack wants
    an ack in 3 seconds and a grounded search takes far longer."""
    from techtrend.platform import queue

    name = rest.strip().lower()
    if not name:
        return "Which one? `/techtrend run <name>`"
    async with session_scope() as s:
        row = (await s.execute(_GET, {"name": name})).one_or_none()
    if row is None:
        return f"`{name}` is not on the watchlist."
    await queue.enqueue("brief", f"brief:manual:{name}:{_bucket()}", {"name": name}, priority=50)
    return f"Researching *{name}* now — the brief will post to the channel shortly."


def _bucket() -> int:
    """A minute bucket, so a double-click is one job and not two."""
    import time

    return int(time.time() // 60)


async def _respond(response_url: str, text_: str) -> None:
    """Reply ephemerally via the response_url Slack hands us.

    No scope needed and only the invoker sees it, which is what a watchlist
    edit should be. A failure here is logged and dropped: the command already
    did its work, and the listener must stay up.
    """
    if not response_url:
        return
    try:
        async with httpx.AsyncClient(timeout=settings().slack_timeout_s) as c:
            await c.post(response_url, json={"response_type": "ephemeral", "text": text_})
    except Exception:  # noqa: BLE001 - the reply, not the command
        telemetry.log.exception("command.reply_failed")
