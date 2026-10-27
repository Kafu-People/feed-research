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
        slack_brief_channel = "C0BRIEFS001"
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
        slack_brief_channel = "C0BRIEFS001"
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


# -------------------------------------------- the progress note (UX)


@pytest.mark.asyncio
async def test_a_progress_note_is_posted_the_moment_a_question_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A grounded answer takes 30 to 120 seconds. A silent minute reads as
    broken, so the note goes out from the LISTENER, not the worker."""
    queued = _on(monkeypatch)
    posted: list[tuple] = []

    class _Client:
        async def post(self, channel, text_, blocks=None, thread_ts=None, unfurl=True):
            posted.append((text_, thread_ts))
            return "note-ts"

    monkeypatch.setattr(discuss, "SlackClient", lambda: _Client())
    await discuss.handle(
        {"channel": "C1", "ts": "2.0", "thread_ts": "1.0", "user": "U1", "text": "what now?"},
        bot_id="B1",
    )
    assert posted == [(discuss.THINKING, "1.0")]
    # The worker is told which message to replace, so the answer does not
    # become a second notification for one question.
    assert queued[0]["note_ts"] == "note-ts"


@pytest.mark.asyncio
async def test_a_failed_note_does_not_lose_the_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The note is best effort. The answer is not."""
    queued = _on(monkeypatch)

    class _Broken:
        async def post(self, *a, **kw):
            raise RuntimeError("slack down")

    monkeypatch.setattr(discuss, "SlackClient", lambda: _Broken())
    await discuss.handle(
        {"channel": "C1", "ts": "2.0", "thread_ts": "1.0", "user": "U1", "text": "what now?"},
        bot_id="B1",
    )
    assert len(queued) == 1
    assert queued[0]["note_ts"] is None


def test_every_giving_up_path_resolves_the_note() -> None:
    """A note that never resolves is worse than no note: the reader waits for
    something that is not coming. Every `return` in `run` that carries no
    answer must go through `_give_up` first."""
    import inspect

    src = inspect.getsource(discuss.run)
    lines = src.split("\n")
    for i, line in enumerate(lines):
        if line.strip() != "return":
            continue
        window = lines[max(0, i - 3) : i]
        # The one exception: the guard before any note exists.
        if any("enabled()" in w for w in window):
            continue
        assert any("_give_up" in w for w in window), f"unresolved note at line {i}"


# ------------------------------- the listener must not fail silently


@pytest.mark.asyncio
async def test_a_dispatch_failure_is_logged_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/techtrend` was dead for two days behind an ImportError.

    Dispatch runs detached, because Slack wants an ack inside 3 seconds and
    the work takes longer. A detached task that raises prints "Task exception
    was never retrieved" to stderr and nothing else -- no stage, no level,
    nothing a log search finds. So the wrapper catches and logs, and the
    listener survives.
    """
    from techtrend.deliver import socket as sock

    logged: list[str] = []

    async def boom(client, envelope, bot_id):
        raise ImportError("cannot import name 'Block'")

    monkeypatch.setattr(sock, "_dispatch", boom)
    monkeypatch.setattr(sock.telemetry.log, "exception", lambda event, **kw: logged.append(event))
    # Must not raise: one bad event never takes the listener down.
    await sock._safe_dispatch(object(), {"type": "slash_commands"}, "B1")
    assert logged == ["slackbot.dispatch_failed"]


def test_the_listener_imports_its_handlers_at_boot() -> None:
    """Lazily importing `commands` inside the dispatcher is what let a stale
    process serve new code against an old module: `slack.py` gained `Block`
    51 minutes AFTER the listener started, and the import failed only when
    somebody finally typed the command. Imported at module scope, that same
    mistake refuses to start."""
    import inspect

    from techtrend.deliver import socket as sock

    src = inspect.getsource(sock._dispatch)
    assert "import" not in src, "handlers must be imported at module scope"
    assert sock.commands is not None
    assert sock.discuss is not None
