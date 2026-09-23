"""Thread discussion in the briefs channel, answered by Gemini.

Two deliberate differences from the Q&A listener in `qa.py`, and they are the
whole reason this is a separate module rather than a branch inside that one.

It answers WITHOUT being mentioned. In the briefs channel a thread under a
brief is a conversation about that brief; making someone type `@techtrend`
first is friction for no benefit, and nobody is chatting in those threads for
any other reason.

And it answers from SEARCH, not from memory. `qa.py` grounds its answer in an
article the crawler already stored, so Haiku reading that text is exactly
right. Here there is no stored article -- the question is about a live
industry -- so the honest answer comes from Google's index at the moment of
asking. A model answering "what does Mercor pay now" from training data is
guessing with confidence, which is the one failure this must not have.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from techtrend.ai import gemini
from techtrend.deliver.slack import SlackClient, to_slack_report
from techtrend.platform import queue, telemetry
from techtrend.platform.config import settings
from techtrend.platform.db import session_scope

# Counted off the queue, like `/techtrend question`: a thread is the easiest
# place to run up a bill, because chatting is cheap for a person andeach answer
# is several billed searches.
_ANSWERED_TODAY = text("""
    SELECT count(*) FROM jobs
     WHERE stage = 'discuss' AND created_at > now() - interval '1 day'
""")

_ASK = """You are answering a question in a chat thread about a research brief
you wrote earlier. The brief and the conversation so far are below.

Answer the LAST message. Ground every factual claim in a web search -- rates,
dates, company news and policies all change, and answering from memory is
guessing. If searching does not settle it, say plainly that you could not
confirm it rather than filling the gap with something plausible.

Never predict or speculate. If someone asks what will happen, say what is
known now and what the people involved have actually announced.

Keep it to a few sentences unless the question genuinely needs more. This is a
chat reply, not a report: no headings, no bullet lists, no tables."""


def enabled() -> bool:
    s = settings()
    return s.gemini_api_key is not None and bool(s.slack_brief_channel) and s.brief_discuss_enabled


async def handle(event: dict[str, Any], *, bot_id: str | None) -> None:
    """Queue an answer for one thread message. Never raises."""
    if not enabled():
        return
    thread_ts = event.get("thread_ts")
    # Top-level messages are not a conversation with anyone. Only replies.
    if not thread_ts or thread_ts == event.get("ts"):
        return
    # Our own posts come back down the socket; answering them is a loop.
    if event.get("bot_id") or event.get("subtype") or event.get("user") is None:
        return
    question = str(event.get("text") or "").strip()
    if len(question) < 3:
        return

    await queue.enqueue(
        "discuss",
        f"discuss:{event.get('channel')}:{event.get('ts')}",
        {
            "channel": event.get("channel"),
            "thread_ts": thread_ts,
            "ts": event.get("ts"),
            "question": question,
        },
        priority=50,
    )


async def run(job: queue.Job) -> None:
    """Research the thread's question and reply in the thread."""
    if not enabled():
        return
    s = settings()
    channel = str(job.payload["channel"])
    thread_ts = str(job.payload["thread_ts"])
    question = str(job.payload["question"])

    async with session_scope() as sess:
        used = (await sess.execute(_ANSWERED_TODAY)).scalar_one()
    if used > s.brief_replies_per_day:
        telemetry.log.warning("discuss.budget_reached", used=used)
        return

    client = SlackClient()
    msgs = await client.replies(channel, thread_ts, limit=s.slack_qa_max_thread_msgs)
    transcript = _transcript(msgs, skip_ts=str(job.payload.get("ts") or ""))

    prompt = f"{_ASK}\n\n<thread>\n{transcript}\n</thread>\n\n<question>\n{question}\n</question>"
    try:
        answer = await gemini.research(prompt)
    except gemini.QuotaExceeded:
        telemetry.log.error("discuss.quota")
        raise
    except Exception:  # noqa: BLE001 - one question, not the listener
        telemetry.log.exception("discuss.failed", thread_ts=thread_ts)
        return

    # `research()` carries the two-part house style, so a thread answer comes
    # back with the ---TABLES--- marker in it. A chat reply is one message:
    # keep both halves, drop the marker that separated them.
    analysis, tables = answer.parts
    body = "\n\n".join(p for p in (analysis, tables) if p.strip())
    if not body:
        return
    # The same gate every other surface applies. This one writes free prose
    # about whatever it just read on the web, so it is the last place a ban
    # could slip through.
    from techtrend.topic.match import blocked, searchable

    if hit := blocked(searchable(body, None, []), s.block_terms):
        telemetry.log.warning("discuss.blocked", term=hit)
        return

    # Truncate the BODY, then append the sources -- the other way round cut a
    # source URL in half, which Slack then rendered as broken markup.
    out = to_slack_report(body)
    if len(out) > 3400:
        out = out[:3400].rstrip() + "\u2026"
        if out.count("```") % 2:
            out += "\n```"
    if answer.sources:
        from techtrend.deliver.brief import _source_line

        out += f"\n\n_{_source_line(answer.sources[:6])}_"
    await client.post(channel, out, thread_ts=thread_ts, unfurl=False)
    telemetry.log.info(
        "discuss.answered", thread_ts=thread_ts, searches=answer.searches, chars=len(body)
    )


def _transcript(msgs: list[dict[str, Any]], *, skip_ts: str) -> str:
    """The thread as plain lines. The question being answered is skipped: it
    is passed separately, and repeating it invites the model to answer the
    one before it."""
    lines = []
    for m in msgs:
        if m.get("ts") == skip_ts:
            continue
        who = "TechTrend" if m.get("bot_id") else "Someone"
        body = str(m.get("text") or "").strip()
        if body:
            lines.append(f"{who}: {body[:1500]}")
    return "\n".join(lines[-20:])
