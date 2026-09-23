"""Thread discussion in the briefs channel, answered by Gemini from search.

The tests that matter here are the ones about what it must NOT answer. A
listener that replies without being mentioned is one bad condition away from
answering itself in a loop, or answering every message in the channel.
"""

from __future__ import annotations

import pytest

from techtrend.deliver import discuss


def _on(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Enable the feature and capture what would be queued."""
    queued: list[dict] = []

    async def fake_enqueue(stage, key, payload=None, **kw):
        queued.append({"stage": stage, "key": key, **(payload or {})})
        return True

    class _S:
        gemini_api_key = "k"
        slack_brief_channel = "#briefs"
        brief_discuss_enabled = True

    monkeypatch.setattr(discuss, "settings", lambda: _S())
    monkeypatch.setattr(discuss.queue, "enqueue", fake_enqueue)
    return queued


@pytest.mark.asyncio
async def test_a_thread_reply_is_answered_without_a_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of the feature. A thread under a brief is a conversation
    about that brief; typing `@techtrend` first is friction for no benefit."""
    queued = _on(monkeypatch)
    await discuss.handle(
        {
            "channel": "C1",
            "ts": "2.0",
            "thread_ts": "1.0",
            "user": "U1",
            "text": "is Mercor still paying that much?",
        },
        bot_id="B1",
    )
    assert len(queued) == 1
    assert queued[0]["question"] == "is Mercor still paying that much?"


@pytest.mark.asyncio
async def test_a_top_level_message_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answering every message in the channel is not a discussion, it is an
    interruption -- and the briefs themselves are top-level messages."""
    queued = _on(monkeypatch)
    await discuss.handle(
        {"channel": "C1", "ts": "1.0", "user": "U1", "text": "morning everyone"}, bot_id="B1"
    )
    # A message whose thread_ts equals its own ts is the thread's parent.
    await discuss.handle(
        {"channel": "C1", "ts": "1.0", "thread_ts": "1.0", "user": "U1", "text": "hello"},
        bot_id="B1",
    )
    assert queued == []


@pytest.mark.asyncio
async def test_its_own_messages_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loop this feature could become: every reply it posts arrives back
    down the same socket as a new thread message."""
    queued = _on(monkeypatch)
    await discuss.handle(
        {
            "channel": "C1",
            "ts": "2.0",
            "thread_ts": "1.0",
            "bot_id": "B1",
            "text": "an answer it just posted",
        },
        bot_id="B1",
    )
    await discuss.handle(
        {
            "channel": "C1",
            "ts": "3.0",
            "thread_ts": "1.0",
            "subtype": "message_changed",
            "user": "U1",
            "text": "edited",
        },
        bot_id="B1",
    )
    assert queued == []


@pytest.mark.asyncio
async def test_it_is_off_until_switched_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """A listener that answers unprompted should be a decision, not something
    that starts happening after a deploy."""

    class _S:
        gemini_api_key = "k"
        slack_brief_channel = "#briefs"
        brief_discuss_enabled = False

    monkeypatch.setattr(discuss, "settings", lambda: _S())
    assert discuss.enabled() is False


def test_the_prompt_forbids_predicting() -> None:
    """The operator's requirement, in the words that carry it: answer from
    search, and say so when search does not settle it."""
    # Whitespace-normalised: the prompt is wrapped, so a phrase that matters
    # can sit across a line break.
    ask = " ".join(discuss._ASK.split())
    assert "Never predict or speculate" in ask
    assert "Ground every factual claim in a web search" in ask
    assert "could not confirm it" in ask


def test_the_question_is_not_repeated_in_the_transcript() -> None:
    """Leaving it in invites the model to answer the message before it."""
    out = discuss._transcript(
        [
            {"ts": "1.0", "text": "the brief", "bot_id": "B1"},
            {"ts": "2.0", "text": "what about pay?", "user": "U1"},
        ],
        skip_ts="2.0",
    )
    assert "the brief" in out
    assert "what about pay?" not in out
    assert out.startswith("TechTrend:")


def test_the_two_part_marker_never_reaches_the_thread() -> None:
    """`research()` carries the house two-part style, so a thread answer
    comes back with the separator in it. A chat reply is one message: keep
    both halves, drop the marker -- it showed literally in the first live
    answer."""
    from techtrend.ai.gemini import TABLES_MARKER, Brief

    answer = Brief(text=f"Mercor pays $84/hr.\n{TABLES_MARKER}\n| Role | Pay |")
    analysis, tables = answer.parts
    body = "\n\n".join(p for p in (analysis, tables) if p.strip())
    assert TABLES_MARKER not in body
    assert "Mercor pays $84/hr." in body
    assert "| Role | Pay |" in body


def test_truncation_cannot_cut_a_source_url_in_half() -> None:
    """The first live answer ended `_<https://vertexaisearch.cloud.g` --
    sources were appended and THEN the whole thing was truncated, so Slack
    got half a link and rendered broken markup."""
    import re

    src = open("src/techtrend/deliver/discuss.py").read()
    body_trunc = src.index("out = out[:3400]")
    append_sources = src.index("_source_line(answer.sources")
    assert body_trunc < append_sources, "sources must be appended after truncation"
    assert re.search(r"out\[:3400\]", src)
