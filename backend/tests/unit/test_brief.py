"""The Gemini brief surface: parsing, gating, and the command grammar.

The gate tests are the point. A brief is prose a model wrote about pages
nobody here fetched -- it is the likeliest way a banned subject reaches the
channel, and the only thing standing in the way is that the block list is
applied to generated text exactly as it is to crawled text.
"""

from __future__ import annotations

import pytest

from techtrend.ai.gemini import Brief, Source, _parse
from techtrend.deliver import brief as brief_mod

# ------------------------------------------------------------ response parsing


def test_parse_pulls_answer_sources_and_search_count() -> None:
    out = _parse(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Rates "}, {"text": "fell."}]},
                    "groundingMetadata": {
                        "groundingChunks": [
                            {"web": {"uri": "https://a", "title": "A"}},
                            {"web": {"uri": "https://b", "title": "B"}},
                        ],
                        "webSearchQueries": ["q1", "q2", "q3"],
                    },
                }
            ]
        }
    )
    assert out.text == "Rates fell."
    assert [s.uri for s in out.sources] == ["https://a", "https://b"]
    # What Google bills for is searches, not prompts -- so that is what the
    # budget counts and what the post footer reports.
    assert out.searches == 3


def test_parse_dedupes_sources() -> None:
    """One answer cites the same page repeatedly; a reader wants a source
    list, not a citation list."""
    out = _parse(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "x"}]},
                    "groundingMetadata": {
                        "groundingChunks": [
                            {"web": {"uri": "https://a", "title": "A"}},
                            {"web": {"uri": "https://a", "title": "A"}},
                        ]
                    },
                }
            ]
        }
    )
    assert len(out.sources) == 1


def test_parse_survives_a_blocked_or_empty_response() -> None:
    """The caller decides whether there is enough to post; it cannot decide
    that from a KeyError."""
    assert _parse({}).text == ""
    assert _parse({"candidates": [{}]}).text == ""


# ------------------------------------------------------------------- the gates


def test_a_banned_publisher_is_dropped_from_sources() -> None:
    """Grounding returns a redirect URL on Google's own host, so the hostname
    cannot answer this -- the real domain arrives in the title."""
    assert brief_mod._banned_source(
        Source(title="bbc.co.uk", uri="https://vertexaisearch.cloud.google.com/redirect/x")
    )
    assert not brief_mod._banned_source(
        Source(title="reddit.com", uri="https://vertexaisearch.cloud.google.com/redirect/y")
    )


def test_render_keeps_the_body_and_links_the_sources() -> None:
    _, blocks = brief_mod._render(
        "dataannotation", "Pay fell.", [Source("reddit.com", "https://r")], 3
    )
    body = "".join(str(b) for b in blocks)
    assert "Pay fell." in body
    assert "https://r" in body
    assert "3 searches" in body


def test_render_escapes_link_text() -> None:
    """A bare | or > inside <url|text> ends the link early."""
    _, blocks = brief_mod._render("x", "body", [Source("a | b > c", "https://r")], 1)
    assert "a ❘ b &gt; c" in "".join(str(b) for b in blocks)


# ------------------------------------------------------------ command grammar


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("dataannotation", True),
        ("data-annotation", True),
        ("ok_1", True),
        ("Data Annotation", False),
        ("a" * 40, False),
        ("", False),
    ],
)
def test_topic_names_are_one_safe_word(name: str, ok: bool) -> None:
    from techtrend.deliver.commands import _NAME

    assert bool(_NAME.match(name)) is ok


@pytest.mark.parametrize(
    ("key", "channel", "on"),
    [(None, None, False), ("k", None, False), (None, "#c", False), ("k", "#c", True)],
)
def test_brief_needs_both_halves(
    monkeypatch: pytest.MonkeyPatch, key: str | None, channel: str | None, on: bool
) -> None:
    """A key with no channel researches into the void; a channel with no key
    posts nothing. Same rule as the Slack card path.

    Built from a stub rather than the environment: the deployed `.env` now has
    both halves set, so reading real settings here tested the deployment and
    not the rule.
    """

    class _S:
        gemini_api_key = key
        slack_brief_channel = channel

    monkeypatch.setattr(brief_mod, "settings", lambda: _S())
    assert brief_mod.configured() is on


# ------------------------------- the block list applies to GENERATED prose


class _Spy:
    def __init__(self) -> None:
        self.posts: list[str] = []

    async def post(self, channel, text_, blocks=None, thread_ts=None, unfurl=True):
        self.posts.append(text_)
        return "1.0"


def _wire(monkeypatch: pytest.MonkeyPatch, text_: str) -> _Spy:
    async def fake_research(prompt: str) -> Brief:
        return Brief(text=text_, sources=[Source("reddit.com", "https://r")], queries=["q"])

    spy = _Spy()
    monkeypatch.setattr(brief_mod.gemini, "research", fake_research)
    monkeypatch.setattr(brief_mod, "SlackClient", lambda: spy)
    monkeypatch.setenv("TT_SLACK_BRIEF_CHANNEL", "#briefs")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return spy


@pytest.mark.asyncio
async def test_a_banned_subject_is_never_posted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The invariant this surface most threatens.

    The prose was written by a model about pages nobody here fetched. If the
    block list is not applied to it, the one path into the channel that skips
    the crawler also skips the ban.
    """
    from techtrend.platform.config import settings

    settings.cache_clear()
    spy = _wire(monkeypatch, "Workers in Tel Aviv report higher rates this week.")
    try:
        spent = await brief_mod._one(spy, "dataannotation", "prompt")
    finally:
        settings.cache_clear()
    assert spy.posts == []  # nothing reached the channel
    assert spent == 1  # but the search was still paid for, and counted


@pytest.mark.asyncio
async def test_ordinary_prose_is_posted(monkeypatch: pytest.MonkeyPatch) -> None:
    from techtrend.platform.config import settings

    settings.cache_clear()
    spy = _wire(monkeypatch, "Annotators report DataAnnotation rates fell to $18/hr.")
    try:
        await brief_mod._one(spy, "dataannotation", "prompt")
    finally:
        settings.cache_clear()
    assert len(spy.posts) == 1


@pytest.mark.asyncio
async def test_quota_exhaustion_stops_the_whole_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A project without billing 429s every grounded call. Treating that as a
    retryable rate limit would hammer it for nothing, so it propagates."""
    from techtrend.ai.gemini import QuotaExceeded
    from techtrend.platform.config import settings

    async def fake_research(prompt: str) -> Brief:
        raise QuotaExceeded("no billing")

    settings.cache_clear()
    spy = _wire(monkeypatch, "unused")
    monkeypatch.setattr(brief_mod.gemini, "research", fake_research)
    try:
        with pytest.raises(QuotaExceeded):
            await brief_mod._one(spy, "x", "prompt")
    finally:
        settings.cache_clear()


def test_sources_are_grouped_by_publisher() -> None:
    """An answer built from forum threads cites one domain many times: the
    first real brief carried 17 sources, all titled `reddit.com`. Twelve
    identical links tell the reader nothing."""
    from techtrend.deliver.brief import _source_line

    line = _source_line(
        [Source("reddit.com", f"https://r/{i}") for i in range(17)]
        + [Source("news.ycombinator.com", "https://h")]
    )
    assert line.count("reddit.com") == 1
    assert "×17" in line
    assert "news.ycombinator.com" in line


# ------------------------------------ the command belongs to ONE channel


@pytest.mark.parametrize(
    ("channel", "allowed"),
    [
        ("techtrend-briefs", True),
        ("techtrend-ai", False),
        ("directmessage", False),
        ("random", False),
    ],
)
def test_command_only_works_in_its_home_channel(
    monkeypatch: pytest.MonkeyPatch, channel: str, allowed: bool
) -> None:
    """Slack offers a slash command in EVERY channel the moment it exists.
    Without this the watchlist is editable from anywhere, including DMs."""
    from techtrend.deliver import commands

    class _S:
        slack_brief_channel = "#techtrend-briefs"

    monkeypatch.setattr(commands, "settings", lambda: _S())
    assert (commands._wrong_channel({"channel_name": channel}) is None) is allowed


def test_command_is_not_refused_everywhere_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No home channel configured must not mean no channel works."""
    from techtrend.deliver import commands

    class _S:
        slack_brief_channel = None

    monkeypatch.setattr(commands, "settings", lambda: _S())
    assert commands._wrong_channel({"channel_name": "anywhere"}) is None


# ------------------------------------------------ edit, question, styling


@pytest.mark.asyncio
async def test_edit_refuses_a_name_it_does_not_know(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole reason `edit` exists beside `add`.

    `add` upserts, so a mistyped name there creates a SECOND topic instead of
    fixing the first. The name is unique, so "change this one" is always
    answerable -- and unanswerable for a name that is not there.
    """
    from techtrend.deliver import commands

    class _Result:
        def one_or_none(self):
            return None

    class _Session:
        async def execute(self, *_a, **_kw):
            return _Result()

    import contextlib

    @contextlib.asynccontextmanager
    async def fake_scope():
        yield _Session()

    monkeypatch.setattr(commands, "session_scope", fake_scope)
    fallback, blocks = await commands._do_edit("nosuch a long enough replacement prompt")
    assert "not on the watchlist" in fallback
    assert any("add" in str(b) for b in blocks)


@pytest.mark.asyncio
async def test_a_short_question_is_refused_before_it_costs_anything() -> None:
    """A grounded question is 4-8 billed searches. `/techtrend question hi`
    must not become one."""
    from techtrend.deliver import commands

    fallback, _ = await commands._do_question("hi", "U1")
    assert "longer" in fallback.lower()


def test_every_reply_is_blocks_not_a_wall_of_text() -> None:
    """Replies are (fallback, blocks). The fallback is what a notification
    shows; the blocks are what gives the reply a shape."""
    from techtrend.deliver.commands import HELP_BLOCKS, _blocks

    out = _blocks(title="T", body="B", note="_n_")
    assert out[0]["type"] == "section"
    assert out[-1]["type"] == "context"
    assert any(b["type"] == "header" for b in HELP_BLOCKS)
    assert "edit" in str(HELP_BLOCKS)


def test_a_long_report_is_split_not_truncated() -> None:
    """A Slack section caps at 3,000 characters, and this used to truncate at
    2,900. The first real research topic produced 17,542 characters, so
    truncating would have thrown away 83% of what was paid for."""
    from techtrend.deliver.brief import _chunk, _render

    body = ("Some paragraph of report text. " * 60 + "\n\n") * 10
    parts = _chunk(body, 2900)
    assert len(parts) > 1
    assert max(len(p) for p in parts) <= 2900
    # Nothing silently vanishes between chunking and rendering.
    _, blocks = _render("aigigwork", body, [], 4)
    delivered = sum(len(b["text"]["text"]) for b in blocks if b["type"] == "section")
    assert delivered >= len(body) * 0.95


def test_a_single_huge_paragraph_still_fits() -> None:
    """Paragraph splitting cannot help when there are no paragraphs."""
    from techtrend.deliver.brief import _chunk

    parts = _chunk("x" * 9000, 2900)
    assert max(len(p) for p in parts) <= 2900
    assert "".join(parts) == "x" * 9000


def test_a_long_prompt_echo_cannot_break_the_reply() -> None:
    """A prompt is free-form. The research spec added here was 2,631
    characters, and echoing one unbounded into a section fails the reply."""
    from techtrend.deliver.commands import _short

    assert len(_short("y" * 5000)) <= 900
    assert _short("short one") == "short one"


# ------------------------------------------ one topic, three rhythms


def test_each_cadence_reads_and_writes_its_own_stamp() -> None:
    """ "Did we do the weekly one yet" cannot be answered by a single
    `last_run_at`, which is why there are three columns."""
    from techtrend.deliver.brief import _DUE_SQL, _MARK_SQL, CADENCES

    assert set(CADENCES) == {"daily", "weekly", "monthly"}
    cols = {c["column"] for c in CADENCES.values()}
    assert cols == {"last_run_at", "last_weekly_at", "last_monthly_at"}
    for name, c in CADENCES.items():
        assert c["column"] in str(_DUE_SQL[name])
        assert c["column"] in str(_MARK_SQL[name])


def test_due_periods_are_under_the_nominal_window() -> None:
    """A job that fired at 08:00:03 yesterday must not read as "not due yet"
    at 08:00:01 today."""
    from datetime import timedelta

    from techtrend.deliver.brief import _period

    assert _period("daily") < timedelta(days=1)
    assert _period("weekly") < timedelta(days=7)
    assert _period("monthly") < timedelta(days=30)


def test_the_window_is_what_makes_a_daily_post_news() -> None:
    """The same topic asked daily must ask for what CHANGED, or it reprints
    yesterday's overview -- measured at 17,542 characters, identical."""
    from techtrend.deliver.brief import CADENCES

    assert "last 24 hours" in CADENCES["daily"]["window"]
    assert "NEW" in CADENCES["daily"]["window"]
    assert "7 days" in CADENCES["weekly"]["window"]
    assert "complete current overview" in CADENCES["monthly"]["window"]


def test_the_header_says_which_rhythm_it_is() -> None:
    from techtrend.deliver.brief import _render

    for cadence, expect in [("daily", "today"), ("weekly", "this week")]:
        _, blocks = _render("aigigwork", "body", [], 1, label=expect)
        assert expect in blocks[0]["text"]["text"], cadence


@pytest.mark.asyncio
async def test_a_one_off_question_gets_no_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """A question is already specific. Appending "only the last 24 hours" to
    it would silently rewrite what the person asked."""
    from techtrend.platform.config import settings

    seen: dict[str, str] = {}

    async def fake_research(prompt: str) -> Brief:
        seen["prompt"] = prompt
        return Brief(text="An answer.", sources=[], queries=["q"])

    settings.cache_clear()
    spy = _wire(monkeypatch, "unused")
    monkeypatch.setattr(brief_mod.gemini, "research", fake_research)
    try:
        await brief_mod._one(spy, "question", "Is Mercor still paying?", heading="Is Mercor...")
    finally:
        settings.cache_clear()
    assert seen["prompt"] == "Is Mercor still paying?"


@pytest.mark.asyncio
async def test_run_defaults_to_daily_and_accepts_a_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`run` used to always mean daily, silently. The rhythm is the whole
    difference between news and a reprint of the overview, so it has to be
    sayable -- and visible in the reply when it was not said."""
    import contextlib

    from techtrend.deliver import commands
    from techtrend.platform import queue

    enqueued: list[dict] = []

    class _Row:
        prompt = "a prompt"

    class _Result:
        def one_or_none(self):
            return _Row()

    class _Session:
        async def execute(self, *_a, **_kw):
            return _Result()

    @contextlib.asynccontextmanager
    async def fake_scope():
        yield _Session()

    async def fake_enqueue(stage, key, payload=None, **kw):
        enqueued.append(payload or {})
        return True

    monkeypatch.setattr(commands, "session_scope", fake_scope)
    monkeypatch.setattr(queue, "enqueue", fake_enqueue)

    fallback, _ = await commands._do_run("aigigwork")
    assert enqueued[-1]["cadence"] == "daily"
    assert "daily" in fallback  # the reply says which one it chose for you

    await commands._do_run("aigigwork monthly")
    assert enqueued[-1]["cadence"] == "monthly"


@pytest.mark.asyncio
async def test_cadence_words_cannot_be_topic_names() -> None:
    """`run <name> monthly` reads the last word as a rhythm, so a topic
    actually called `monthly` could never be run on its own."""
    from techtrend.deliver import commands

    fallback, _ = await commands._do_add("monthly a long enough prompt to pass", "U1")
    assert "Reserved" in fallback
