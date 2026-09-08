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


# ------------------------------------------- hourly batching (2026-09-08)


def test_delay_to_boundary_lands_on_the_hour() -> None:
    """Cards wait for the interval boundary so an hour's worth post together."""
    from techtrend.topic.worker import _delay_to_boundary

    # 10:00:00 exactly -> a full hour to the next boundary, never 0, or a
    # story matched on the hour would post immediately and miss its batch.
    assert _delay_to_boundary(now=3600.0 * 10) == 3600.0
    # 10:59:00 -> 60s. The 10:01 story and this one wake in the same claim.
    assert _delay_to_boundary(now=3600.0 * 10 + 3540) == 60.0


def test_interval_zero_restores_immediate_posting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The old behaviour is still reachable, and is exactly delay 0."""
    from techtrend.platform.config import settings
    from techtrend.topic.worker import _delay_to_boundary

    monkeypatch.setenv("TT_SLACK_POST_INTERVAL_HOURS", "0")
    settings.cache_clear()
    try:
        assert _delay_to_boundary(now=1234.5) == 0.0
    finally:
        settings.cache_clear()


@pytest.mark.asyncio
async def test_batch_returns_one_entry_per_story() -> None:
    """The batch path's contract: a mapping keyed by story id, values that may
    be None. The caller reads `summary_ts IS NULL` as its work queue, so a
    missing key and a None must both leave the story retryable."""
    from techtrend.ai.fake import FakeAIClient

    out = await FakeAIClient().summarize_batch(
        [(1, "Long one", "x" * 500), (2, "Thin one", "short")]
    )
    assert set(out) == {1, 2}
    assert out[1] is not None
    assert out[2] is None  # declined, and stays unsummarised


def test_batch_pending_carries_the_receipt() -> None:
    """A batch that outlives the poll is not a failure -- the id is how the
    follow-up job collects it instead of paying for the work twice."""
    from techtrend.ai.claude import BatchPending

    assert BatchPending("msgbatch_123").batch_id == "msgbatch_123"


# ------------------------------------------- the hourly report (2026-09-08)


class _Row:
    """The columns `_render` reads. A namespace, not a model -- the query
    returns a row, and the renderer must not care which."""

    def __init__(self, **kw: object) -> None:
        self.__dict__.update(
            {
                "id": 1,
                "title": "T",
                "url": "https://e.com/a",
                "site": "Example",
                "source_count": 1,
                "topic_ids": [3],
                "topic_titles": ["AI models & labs"],
                "scores": [0.8],
                **kw,
            }
        )


def test_report_decodes_entities_before_escaping() -> None:
    """A title arrives as `Here&#8217;s`. Escaping that without decoding first
    ships a literal `&amp;#8217;` -- the trap slack.py's `_esc` documents."""
    from datetime import UTC, datetime

    from techtrend.deliver.hourly import _render

    now = datetime.now(UTC)
    _, blocks = _render([_Row(title="Here&#8217;s the news &mdash; really")], {1: "S."}, now, now)
    body = "".join(b["text"]["text"] for b in blocks if b["type"] == "section")
    assert "&#8217;" not in body
    assert "&mdash;" not in body
    assert "Here\u2019s the news \u2014 really" in body


def test_report_link_text_cannot_break_slack_markup() -> None:
    """A bare | or > inside <url|text> ends the link early."""
    from datetime import UTC, datetime

    from techtrend.deliver.hourly import _render

    now = datetime.now(UTC)
    _, blocks = _render([_Row(title="A | B > C")], {1: "S."}, now, now)
    link = [b for b in blocks if b["type"] == "section"][0]["text"]["text"]
    assert "A ❘ B &gt; C" in link


def test_report_carries_the_summary_under_the_link() -> None:
    """The whole point of the format: link and summary in one message."""
    from datetime import UTC, datetime

    from techtrend.deliver.hourly import _render

    now = datetime.now(UTC)
    _, blocks = _render([_Row()], {1: "The plain-language version."}, now, now)
    body = [b for b in blocks if b["type"] == "section"][0]["text"]["text"]
    assert "https://e.com/a" in body
    assert "The plain-language version." in body


def test_report_survives_a_story_with_no_summary() -> None:
    """A declined summary loses the prose, never the link."""
    from datetime import UTC, datetime

    from techtrend.deliver.hourly import _render

    now = datetime.now(UTC)
    _, blocks = _render([_Row()], {}, now, now)
    body = [b for b in blocks if b["type"] == "section"][0]["text"]["text"]
    assert "https://e.com/a" in body
