"""Slack delivery units: message rendering and the error taxonomy.

No I/O: httpx is mocked with respx, exactly as the collect units do it.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from techtrend.deliver.slack import SlackClient, followup_text, story_blocks
from techtrend.platform import queue
from techtrend.platform.config import settings

API = "https://slack.com/api/chat.postMessage"


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TT_SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("TT_SLACK_CHANNEL", "#tech-updates")
    settings.cache_clear()
    yield
    settings.cache_clear()


def _blocks(**kw):
    base = {"title": "T", "url": "https://ex.com/a", "site": "S", "source_count": 1, "topics": []}
    return story_blocks(**{**base, **kw})


# ------------------------------------------------------------------ rendering


def test_card_is_the_link_and_its_provenance() -> None:
    fallback, blocks = _blocks(
        title="OpenAI ships a thing", source_count=3, topics=["AI models & labs"], site="The Verge"
    )
    assert fallback == "OpenAI ships a thing"
    assert blocks[0]["text"]["text"] == "<https://ex.com/a|*OpenAI ships a thing*>"
    ctx = blocks[1]["elements"][0]["text"]
    assert "The Verge" in ctx and "3 sources" in ctx and "`AI models &amp; labs`" in ctx


def test_card_never_repeats_what_the_unfurl_renders() -> None:
    """The blurb and the image belong to Slack's preview, not to our message."""
    _, blocks = _blocks(title="T")
    assert len(blocks) == 2  # section + context, nothing else
    assert "accessory" not in blocks[0]
    assert all(b["type"] != "image" for b in blocks)


def test_single_source_story_omits_the_source_count() -> None:
    _, blocks = _blocks(source_count=1)
    assert "sources" not in blocks[1]["elements"][0]["text"]


def test_slack_markup_characters_are_escaped() -> None:
    _, blocks = _blocks(title="Nvidia <b> & AMD")
    text = blocks[0]["text"]["text"]
    assert "&lt;b&gt;" in text and "&amp;" in text and "<b>" not in text


def test_publisher_html_entities_are_decoded_before_escaping() -> None:
    """Feed titles carry raw entities; double-escaping ships literal "&#8220;"."""
    _, blocks = _blocks(title="&#8220;The unraveling&#8221; of a lab &amp; its rivals")
    text = blocks[0]["text"]["text"]
    assert "“The unraveling”" in text
    assert "&amp;#8220;" not in text
    assert "&amp;" in text  # the real ampersand is still escaped for Slack


def test_long_titles_are_truncated_not_rejected() -> None:
    fallback, _ = _blocks(title="x" * 500)
    assert len(fallback) == 200 and fallback.endswith("…")


def test_followup_names_the_new_source_count() -> None:
    assert "*5*" in followup_text(5)


# ------------------------------------------------------------------- posting


@respx.mock
@pytest.mark.asyncio
async def test_unfurling_is_enabled_so_slack_renders_the_preview() -> None:
    route = respx.post(API).mock(return_value=httpx.Response(200, json={"ok": True, "ts": "1"}))
    await SlackClient().post("#c", "hi")
    body = json.loads(route.calls.last.request.read())
    assert body["unfurl_links"] is True
    assert body["unfurl_media"] is True


@respx.mock
@pytest.mark.asyncio
async def test_post_returns_ts_on_success() -> None:
    respx.post(API).mock(return_value=httpx.Response(200, json={"ok": True, "ts": "17.99"}))
    assert await SlackClient().post("#c", "hi") == "17.99"


@respx.mock
@pytest.mark.asyncio
async def test_thread_ts_is_forwarded_for_followups() -> None:
    route = respx.post(API).mock(return_value=httpx.Response(200, json={"ok": True, "ts": "2"}))
    await SlackClient().post("#c", "more", thread_ts="1")
    body = json.loads(route.calls.last.request.read())
    assert body["thread_ts"] == "1"
    assert "blocks" not in body  # a follow-up is plain text in-thread


@respx.mock
@pytest.mark.asyncio
async def test_bad_config_is_fatal_not_retried() -> None:
    respx.post(API).mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "channel_not_found"})
    )
    with pytest.raises(queue.FatalError):
        await SlackClient().post("#c", "hi")


@respx.mock
@pytest.mark.asyncio
async def test_rate_limit_is_retryable() -> None:
    respx.post(API).mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "ratelimited"})
    )
    with pytest.raises(queue.RetryableError):
        await SlackClient().post("#c", "hi")


@respx.mock
@pytest.mark.asyncio
async def test_network_failure_is_retryable() -> None:
    respx.post(API).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(queue.RetryableError):
        await SlackClient().post("#c", "hi")


@pytest.mark.asyncio
async def test_missing_token_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic on purpose: unsetting the env var is not enough, because
    pydantic still reads backend/.env -- which on a deployed box holds a real
    token. Build a Settings with the file source switched off instead."""
    from techtrend.deliver import slack as slack_mod
    from techtrend.platform.config import Settings

    monkeypatch.setattr(
        slack_mod, "settings", lambda: Settings(slack_bot_token=None, _env_file=None)
    )
    with pytest.raises(queue.FatalError):
        slack_mod.SlackClient()
