"""Summary units: the guards that keep a summary from costing us the card."""

from __future__ import annotations

import pytest

from techtrend.deliver import worker as nw
from techtrend.platform.config import settings


class _Spy:
    """Stands in for SlackClient; records what would have been posted."""

    def __init__(self) -> None:
        self.posts: list[dict[str, object]] = []

    async def post(self, channel, text, blocks=None, thread_ts=None):
        self.posts.append({"channel": channel, "text": text, "thread_ts": thread_ts})
        return "9.9"


@pytest.fixture(autouse=True)
def _clear():
    settings.cache_clear()
    yield
    settings.cache_clear()


def _wire(monkeypatch, *, body: bytes | Exception, summary: str | None | Exception):
    def fake_get(_key: str) -> bytes:
        if isinstance(body, Exception):
            raise body
        return body

    class _AI:
        async def summarize(self, title: str, text: str) -> str | None:
            if isinstance(summary, Exception):
                raise summary
            return summary

    monkeypatch.setattr(nw.blobs, "get", fake_get)
    monkeypatch.setattr(nw, "ai_client", lambda: _AI())


async def _run(spy, **kw):
    await nw._reply_summary(
        spy, "#c", "1.0", story_id=1, title="T", text_key=kw.pop("text_key", "text/ab/cd")
    )


@pytest.mark.asyncio
async def test_summary_posts_in_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TT_SLACK_SUMMARIES", "true")
    _wire(monkeypatch, body=b"x" * 2000, summary="A plain sentence about the news.")
    spy = _Spy()
    await _run(spy)
    assert len(spy.posts) == 1
    assert spy.posts[0]["thread_ts"] == "1.0"  # a reply, never a second card
    assert spy.posts[0]["text"] == "A plain sentence about the news."


@pytest.mark.asyncio
async def test_disabled_setting_spends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TT_SLACK_SUMMARIES", "false")

    def boom(_key: str) -> bytes:
        raise AssertionError("must not touch blob storage when disabled")

    monkeypatch.setattr(nw.blobs, "get", boom)
    spy = _Spy()
    await _run(spy)
    assert spy.posts == []


@pytest.mark.asyncio
async def test_thin_extraction_is_not_summarised(monkeypatch: pytest.MonkeyPatch) -> None:
    """A paywall notice is short; summarising it would read as a real article."""
    monkeypatch.setenv("TT_SLACK_SUMMARIES", "true")
    monkeypatch.setenv("TT_SLACK_SUMMARY_MIN_CHARS", "600")

    class _AI:
        async def summarize(self, *_: object) -> str:
            raise AssertionError("must not call the model on thin text")

    monkeypatch.setattr(nw.blobs, "get", lambda _k: b"Subscribe to continue reading.")
    monkeypatch.setattr(nw, "ai_client", lambda: _AI())
    spy = _Spy()
    await _run(spy)
    assert spy.posts == []


@pytest.mark.asyncio
async def test_missing_text_key_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TT_SLACK_SUMMARIES", "true")
    _wire(monkeypatch, body=b"x" * 2000, summary="unused")
    spy = _Spy()
    await _run(spy, text_key=None)
    assert spy.posts == []


@pytest.mark.asyncio
async def test_model_declining_posts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The prompt's SKIP path returns None — that is a silent no-op, not a reply."""
    monkeypatch.setenv("TT_SLACK_SUMMARIES", "true")
    _wire(monkeypatch, body=b"x" * 2000, summary=None)
    spy = _Spy()
    await _run(spy)
    assert spy.posts == []


@pytest.mark.asyncio
async def test_model_failure_never_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """The card is already posted and recorded; a raise here would retry the job."""
    monkeypatch.setenv("TT_SLACK_SUMMARIES", "true")
    _wire(monkeypatch, body=b"x" * 2000, summary=RuntimeError("api down"))
    spy = _Spy()
    await _run(spy)  # must not raise
    assert spy.posts == []


@pytest.mark.asyncio
async def test_blob_failure_never_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TT_SLACK_SUMMARIES", "true")
    _wire(monkeypatch, body=OSError("blob gone"), summary="unused")
    spy = _Spy()
    await _run(spy)  # must not raise
    assert spy.posts == []


@pytest.mark.asyncio
async def test_fake_client_declines_thin_text() -> None:
    from techtrend.ai.fake import FakeAIClient

    assert await FakeAIClient().summarize("T", "short") is None
    assert await FakeAIClient().summarize("T", "x" * 500) is not None
