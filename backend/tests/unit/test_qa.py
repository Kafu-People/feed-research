"""Q&A units: what the bot answers, and what it refuses to guess at."""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

from techtrend.deliver import qa


class _Spy:
    def __init__(self, replies: list[dict[str, Any]] | None = None) -> None:
        self.posts: list[dict[str, Any]] = []
        self._replies = replies or []

    async def post(self, channel, text, blocks=None, thread_ts=None):
        self.posts.append({"channel": channel, "text": text, "thread_ts": thread_ts})
        return "9.9"

    async def replies(self, channel, thread_ts, limit=30):
        return self._replies


def _story(monkeypatch, row: Any) -> None:
    """Stand in for the thread_ts -> story lookup."""

    class _Result:
        def one_or_none(self):
            return row

    class _Session:
        async def execute(self, *_a, **_kw):
            return _Result()

    @contextlib.asynccontextmanager
    async def fake_scope():
        yield _Session()

    monkeypatch.setattr(qa, "session_scope", fake_scope)


class _Row:
    id, title, text_key = 42, "A headline", "text/ab/cd"


def _ai(monkeypatch, *, answer: str | Exception = "Because the article says so.") -> None:
    class _AI:
        async def answer(self, question, title, body, thread):
            if isinstance(answer, Exception):
                raise answer
            return answer

    monkeypatch.setattr(qa, "ai_client", lambda: _AI())
    monkeypatch.setattr(qa.blobs, "get", lambda _k: b"x" * 3000)


# ------------------------------------------------------------------- parsing


def test_strip_mentions_leaves_the_question() -> None:
    assert qa.strip_mentions("<@U123ABC> what does this mean?") == "what does this mean?"


def test_strip_mentions_handles_a_mention_mid_sentence() -> None:
    """Whitespace collapses, so the model does not see a gap in the question."""
    assert qa.strip_mentions("hey <@U1> is this new?") == "hey is this new?"


def test_strip_mentions_collapses_newlines_too() -> None:
    assert qa.strip_mentions("<@U1>\n\nwhat  changed?") == "what changed?"


def test_render_thread_labels_the_bot_and_skips_the_question() -> None:
    msgs = [
        {"ts": "1", "text": "the summary", "bot_id": "B1"},
        {"ts": "2", "text": "what do you think?"},
        {"ts": "3", "text": "<@U9> explain"},
    ]
    out = qa.render_thread(msgs, bot_id="B1", skip_ts="3")
    assert "TechTrend: the summary" in out
    assert "someone: what do you think?" in out
    assert "explain" not in out  # the question itself is passed separately


def test_render_thread_drops_empty_messages() -> None:
    msgs = [{"ts": "1", "text": "<@U9>"}, {"ts": "2", "text": "real content"}]
    assert qa.render_thread(msgs, bot_id=None, skip_ts=None) == "someone: real content"


# ------------------------------------------------------------------ handling


@pytest.mark.asyncio
async def test_mention_outside_a_thread_is_redirected(monkeypatch: pytest.MonkeyPatch) -> None:
    """No thread means no article; say so rather than answering from memory."""
    spy = _Spy()
    await qa.handle_mention(spy, {"channel": "C1", "ts": "5.0", "text": "<@U1> hi"})
    assert spy.posts[0]["text"] == qa.NOT_A_STORY_THREAD
    assert spy.posts[0]["thread_ts"] == "5.0"  # replies to them, not to the channel


@pytest.mark.asyncio
async def test_bare_mention_asks_for_a_question(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _Spy()
    await qa.handle_mention(
        spy, {"channel": "C1", "ts": "5.0", "thread_ts": "1.0", "text": "<@U1>"}
    )
    assert spy.posts[0]["text"] == qa.NO_QUESTION


@pytest.mark.asyncio
async def test_thread_with_no_story_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _story(monkeypatch, None)
    spy = _Spy()
    await qa.handle_mention(
        spy, {"channel": "C1", "ts": "5.0", "thread_ts": "1.0", "text": "<@U1> why?"}
    )
    assert spy.posts[0]["text"] == qa.NOT_A_STORY_THREAD


@pytest.mark.asyncio
async def test_answer_is_posted_into_the_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    _story(monkeypatch, _Row())
    _ai(monkeypatch, answer="It means `latency` drops.")
    spy = _Spy(replies=[{"ts": "1.0", "text": "the summary", "bot_id": "B1"}])
    await qa.handle_mention(
        spy, {"channel": "C1", "ts": "5.0", "thread_ts": "1.0", "text": "<@U1> what changed?"}
    )
    assert len(spy.posts) == 1
    assert spy.posts[0]["thread_ts"] == "1.0"
    assert spy.posts[0]["text"] == "It means `latency` drops."


@pytest.mark.asyncio
async def test_markdown_in_an_answer_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    _story(monkeypatch, _Row())
    _ai(monkeypatch, answer="It affects **latency** most.")
    spy = _Spy()
    await qa.handle_mention(
        spy, {"channel": "C1", "ts": "5.0", "thread_ts": "1.0", "text": "<@U1> what?"}
    )
    assert spy.posts[0]["text"] == "It affects `latency` most."


@pytest.mark.asyncio
async def test_model_failure_reports_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad question must not take down the listener for everyone else."""
    _story(monkeypatch, _Row())
    _ai(monkeypatch, answer=RuntimeError("api down"))
    spy = _Spy()
    await qa.handle_mention(
        spy, {"channel": "C1", "ts": "5.0", "thread_ts": "1.0", "text": "<@U1> what?"}
    )
    assert "went wrong" in spy.posts[0]["text"]
    assert spy.posts[0]["thread_ts"] == "1.0"


@pytest.mark.asyncio
async def test_event_missing_channel_is_ignored() -> None:
    spy = _Spy()
    await qa.handle_mention(spy, {"text": "<@U1> hi"})
    assert spy.posts == []
