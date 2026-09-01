"""Slack delivery units: message rendering and the error taxonomy.

No I/O: httpx is mocked with respx, exactly as the collect units do it.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
import respx

from techtrend.deliver.slack import SlackClient, followup_text, story_blocks, to_mrkdwn
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


def test_fallback_text_is_decoded_too() -> None:
    """The fallback is Slack's push-notification text, not a spare copy.

    A raw `&#8217;` here reaches every phone in the channel even though the
    rendered block looks fine.
    """
    fallback, blocks = _blocks(title="Here&#8217;s why it matters")
    assert fallback == "Here\u2019s why it matters"
    assert "&#8217;" not in fallback


def test_fallback_truncation_never_slices_an_entity() -> None:
    """Decode before truncating, so the 200-char cut lands on real characters.

    Escaping first would expand & to &amp; and the cut could then land inside
    it, shipping a dangling `&am`. Note the escaped result may exceed 200 chars
    for that reason -- the limit is on the decoded text, well under Slack's own.
    """
    fallback, _ = _blocks(title="x" * 195 + " a &amp; b")
    assert "&amp;" in fallback
    # Every & in the output opens a complete entity; none is a sliced fragment.
    assert re.search(r"&(?!amp;|lt;|gt;)", fallback) is None


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
async def test_unfurling_can_be_switched_off_per_message() -> None:
    """The digest links to Slack permalinks, and Slack expands those into
    quoted copies of the linked message -- which would bury the digest."""
    route = respx.post(API).mock(return_value=httpx.Response(200, json={"ok": True, "ts": "1"}))
    await SlackClient().post("#c", "hi", unfurl=False)
    body = json.loads(route.calls.last.request.read())
    assert body["unfurl_links"] is False
    assert body["unfurl_media"] is False


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


# --------------------------------------------------------- mrkdwn normalising


def test_markdown_bold_folds_to_a_code_span() -> None:
    """Highlighting is a backticked span; emphasis in any dialect becomes one."""
    assert to_mrkdwn("OpenAI will **go public** soon.") == "OpenAI will `go public` soon."


def test_slack_bold_folds_to_a_code_span() -> None:
    assert to_mrkdwn("OpenAI will *go public* soon.") == "OpenAI will `go public` soon."


def test_existing_code_spans_are_left_alone() -> None:
    assert to_mrkdwn("already `correct` here") == "already `correct` here"


def test_multiple_spans_all_convert() -> None:
    assert to_mrkdwn("**Anthropic** raised **$2bn**") == "`Anthropic` raised `$2bn`"


def test_headings_and_bullets_are_stripped() -> None:
    assert to_mrkdwn("# The Gist\nSome text") == "The Gist\nSome text"
    assert to_mrkdwn("- a bullet") == "a bullet"


def test_underscores_fold_to_a_code_span() -> None:
    assert to_mrkdwn("a __span__ here") == "a `span` here"


def test_lone_asterisks_are_not_mangled() -> None:
    """A footnote marker or a *.py glob must survive, not become markup.

    This is what the \\S lookarounds in the emphasis patterns are protecting.
    """
    assert to_mrkdwn("the file *.py and a * alone") == "the file *.py and a * alone"


def test_a_bullet_line_is_not_read_as_emphasis() -> None:
    """`* item` opens with an asterisk but is a list marker, not a bold span."""
    assert to_mrkdwn("* first item") == "first item"


# --------------------------------------------------------- per-topic floors


def test_floor_falls_back_to_the_global_value(monkeypatch: pytest.MonkeyPatch) -> None:
    from techtrend.deliver.worker import floor_for

    monkeypatch.setenv("TT_SLACK_MATCH_FLOOR", "0.6")
    monkeypatch.delenv("TT_SLACK_TOPIC_FLOORS", raising=False)
    settings.cache_clear()
    assert floor_for(3) == 0.6


def test_per_topic_floor_overrides_the_global(monkeypatch: pytest.MonkeyPatch) -> None:
    """Job listings score lower than news; one global bar cannot serve both."""
    from techtrend.deliver.worker import floor_for

    monkeypatch.setenv("TT_SLACK_MATCH_FLOOR", "0.6")
    monkeypatch.setenv("TT_SLACK_TOPIC_FLOORS", '{"15": 0.5}')
    settings.cache_clear()
    assert floor_for(15) == 0.5  # overridden
    assert floor_for(3) == 0.6  # untouched
