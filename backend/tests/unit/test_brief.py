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
        self.threads: list[str | None] = []

    async def post(self, channel, text_, blocks=None, thread_ts=None, unfurl=True):
        self.posts.append(text_)
        self.threads.append(thread_ts)
        return "1.0"


def _wire(monkeypatch: pytest.MonkeyPatch, text_: str) -> _Spy:
    """Stub everything outside the module under test -- including the DB.

    `_one` stamps `last_run_at` on success, which opened a real asyncpg
    connection from a unit test. It passed alone and failed in the suite with
    "attached to a different loop", because the pool outlives one test's event
    loop. A unit test has no business reaching Postgres.
    """
    import contextlib

    async def fake_research(prompt: str) -> Brief:
        return Brief(text=text_, sources=[Source("reddit.com", "https://r")], queries=["q"])

    class _Session:
        async def execute(self, *_a, **_kw):
            return None

    @contextlib.asynccontextmanager
    async def fake_scope():
        yield _Session()

    spy = _Spy()
    monkeypatch.setattr(brief_mod.gemini, "research", fake_research)
    monkeypatch.setattr(brief_mod, "SlackClient", lambda: spy)
    monkeypatch.setattr(brief_mod, "session_scope", fake_scope)
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
    # One post: this fixture's answer carries no marker, so there is no
    # tables half to post.
    assert len(spy.posts) == 1


@pytest.mark.asyncio
async def test_both_readings_are_posted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator's shape: the write-up AND the same findings as tables,
    as two ordinary posts.

    They answer different questions -- understanding wants paragraphs,
    deciding wants a grid -- and one research call produces both, so nobody
    has to choose and the second post is free. Not a thread: a thread hides
    the tables behind a click, and the tables are usually the point.
    """
    from techtrend.ai.gemini import TABLES_MARKER
    from techtrend.platform.config import settings

    text = f"Rates fell this week.\n{TABLES_MARKER}\n| Platform | Pay |\n| --- | --- |"
    settings.cache_clear()
    spy = _wire(monkeypatch, text)
    try:
        await brief_mod._one(spy, "dataannotation", "prompt")
    finally:
        settings.cache_clear()
    assert len(spy.posts) == 2
    assert all(t is None for t in spy.threads)  # both top level, no thread
    assert "tables" in spy.posts[-1]


def test_a_brief_without_the_marker_still_posts() -> None:
    """The split is the model following an instruction, so it can be missed.
    Prose alone is still worth posting."""
    from techtrend.ai.gemini import Brief

    analysis, tables = Brief(text="Only prose here.").parts
    assert analysis == "Only prose here."
    assert tables == ""


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


# ------------------------------------------------ structure, not a wall


def test_headings_survive_into_slack_bold() -> None:
    """Slack has no heading syntax, so a heading becomes a bold line on its
    own -- which is what `to_mrkdwn` was DELETING before briefs had their own
    renderer."""
    from techtrend.deliver.slack import to_slack_report

    out = to_slack_report("## 1. Industry Trends\n\nDemand **grew**.")
    assert "*1. Industry Trends*" in out
    assert "#" not in out
    assert "*grew*" in out


def test_bullets_become_real_bullets() -> None:
    """`- item` renders in Slack as a dash. `\u2022 item` renders as a list."""
    from techtrend.deliver.slack import to_slack_report

    out = to_slack_report("- Coders: $40/hr\n- Doctors: $90/hr")
    assert out.count("\u2022") == 2
    assert not out.startswith("-")


def test_a_heading_keeps_the_blank_line_after_it() -> None:
    """`\\s*$` matches newlines, so the first version welded every heading to
    the paragraph beneath it."""
    from techtrend.deliver.slack import to_slack_report

    assert "*Outlook*\n\nSteady" in to_slack_report("## Outlook\n\nSteady")


def test_the_report_is_split_at_its_own_headings() -> None:
    """Chunking by length alone breaks at whatever 2,900 characters lands on,
    which reads as a glitch rather than a section."""
    from techtrend.deliver.brief import _body_blocks

    body = "*1. One*\n\nalpha\n\n*2. Two*\n\nbeta\n\n*3. Three*\n\ngamma"
    assert [b["type"] for b in _body_blocks(body)] == [
        "section",
        "divider",
        "section",
        "divider",
        "section",
    ]


def test_a_short_answer_gets_no_dividers() -> None:
    """A daily answer is a few paragraphs with no headings. Slicing it up
    would invent structure the model did not write."""
    from techtrend.deliver.brief import _body_blocks

    assert [b["type"] for b in _body_blocks("Two sentences.\n\nAnd another.")] == ["section"]


# ------------------------------------------------ tables that actually align


def test_a_markdown_table_becomes_a_monospace_block() -> None:
    """Slack renders NO table. A pipe grid posted as mrkdwn is literal text in
    a PROPORTIONAL font, so the columns wander -- which is what shipped and
    what the operator saw. A fenced block is the one place Slack uses a
    fixed-width font."""
    from techtrend.deliver.slack import to_slack_report

    out = to_slack_report(
        "| Platform | Pay |\n| :--- | :--- |\n| **Outlier** | $15 |\n| Mercor | $180 |"
    )
    assert out.startswith("```")
    assert out.rstrip().endswith("```")
    lines = [ln for ln in out.split("\n") if ln and "`" not in ln]
    # Header, rule, two rows -- and every row padded to the same width.
    assert len(lines) == 4
    assert len({len(ln.rstrip()) for ln in lines}) > 0
    assert lines[0].startswith("Platform")
    assert set(lines[1]) <= {"-", " "}


def test_table_cells_lose_their_emphasis() -> None:
    """Slack renders no bold inside a code block, so `*Outlier*` would show
    its asterisks."""
    from techtrend.deliver.slack import to_slack_report

    out = to_slack_report("| A |\n| :--- |\n| **Outlier** |")
    assert "Outlier" in out
    assert "*" not in out


def test_the_separator_row_is_not_transcribed() -> None:
    """`| :--- | :--- |` is drawing, not data."""
    from techtrend.deliver.slack import to_slack_report

    assert ":---" not in to_slack_report("| A | B |\n| :--- | :--- |\n| 1 | 2 |")


def test_a_split_table_keeps_its_fences() -> None:
    """A long table exceeds one 3,000-character block. Without repair the
    first piece opens a fence it never closes, the MIDDLE pieces carry no
    fence at all and render as the unaligned text the block existed to fix,
    and the last closes a fence nobody opened."""
    from techtrend.deliver.brief import _chunk

    fence = "```"
    body = f"{fence}\n" + ("a padded row of table data\n" * 400) + fence
    parts = _chunk(body, 2900)
    assert len(parts) > 2
    for part in parts:
        assert part.count(fence) % 2 == 0, "unbalanced fence"
        assert part.lstrip().startswith(fence), "a piece that is not marked as code"


def test_entities_are_decoded_inside_the_fence() -> None:
    """Slack decodes entities in ordinary mrkdwn but NOT inside a code block,
    so `&amp;` showed its own markup in the posted table -- and skewed the
    padding, since it measures five characters where `&` measures one."""
    from techtrend.deliver.slack import to_slack_report

    out = to_slack_report("| A |\n| :--- |\n| Generalists &amp; Coders |")
    assert "&amp;" not in out
    assert "Generalists & Coders" in out


def test_the_prompt_asks_part_one_for_prose_and_part_two_for_tables() -> None:
    """Two readings, two shapes, and the operator settled both.

    Part one was briefly written as headings and bullets. That chops an
    explanation into fragments and leaves the reader to reassemble it -- so
    part one is prose that connects its facts, and every list lives in part
    two as a table.
    """
    from techtrend.ai.gemini import _STYLE

    part_one = _STYLE[_STYLE.index("PART ONE") : _STYLE.index("PART TWO")]
    assert "NO bullet points" in part_one
    assert "NO numbered lists" in part_one
    assert "NO headings" in part_one
    assert "Flowing paragraphs" in part_one

    part_two = _STYLE[_STYLE.index("PART TWO") :]
    assert "tables" in part_two
    assert "Four or\nfive columns at most" in part_two


def test_a_long_cell_wraps_and_loses_nothing() -> None:
    """The first version cut cells at 24 characters with an ellipsis, which
    threw away the half of every sentence that carried the point -- and a
    chat message offers nothing to click to see the rest."""
    from techtrend.deliver.slack import to_slack_report

    long = "Meta bought 49% of Scale AI for $14.3 billion in 2025"
    out = to_slack_report(f"| Metric | Details |\n| :--- | :--- |\n| Deal | {long} |")
    assert "\u2026" not in out
    # Every word survives, spread over continuation lines.
    flat = " ".join(out.split())
    for word in ("Meta", "49%", "Scale", "$14.3", "billion", "2025"):
        assert word in flat


def test_wrapped_rows_stay_aligned() -> None:
    """Wrapping is only useful if the columns still line up under it."""
    from techtrend.deliver.slack import to_slack_report

    out = to_slack_report(
        "| A | B |\n| :--- | :--- |\n| short | a much longer cell that has to wrap somewhere |"
    )
    body = [ln for ln in out.split("\n") if ln and "`" not in ln]
    rule = body[1]
    assert set(rule) <= {"-", " "}
    # The second column starts at the same offset on the header and the rule.
    assert body[0].index("B") == rule.index(" ") + 2


# ------------------------------------------- busy is not broken


@pytest.mark.asyncio
async def test_a_busy_model_falls_back_to_the_smaller_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Google's flash models go unavailable in spikes -- two consecutive runs
    hit "This model is currently experiencing high demand". An answer from
    the smaller model beats no answer today."""
    from techtrend.ai import gemini

    tried: list[str] = []

    async def fake_ask(prompt: str, model: str) -> Brief:
        tried.append(model)
        if len(tried) == 1:
            raise gemini.Transient("gemini 503")
        return Brief(text="answered by the fallback")

    class _S:
        gemini_model = "primary"
        gemini_fallback_model = "secondary"

    monkeypatch.setattr(gemini, "_ask", fake_ask)
    monkeypatch.setattr(gemini, "settings", lambda: _S())
    out = await gemini.research("q")
    assert tried == ["primary", "secondary"]
    assert out.text == "answered by the fallback"


@pytest.mark.asyncio
async def test_no_fallback_configured_means_the_error_stands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from techtrend.ai import gemini

    async def always_busy(prompt: str, model: str) -> Brief:
        raise gemini.Transient("gemini 503")

    class _S:
        gemini_model = "primary"
        gemini_fallback_model = ""

    monkeypatch.setattr(gemini, "_ask", always_busy)
    monkeypatch.setattr(gemini, "settings", lambda: _S())
    with pytest.raises(gemini.Transient):
        await gemini.research("q")


def test_transient_is_not_quota() -> None:
    """A quota error means billing is off and retrying changes nothing; a
    transient means try again shortly. Without the split, one busy afternoon
    cost a topic its entire day."""
    from techtrend.ai.gemini import QuotaExceeded, Transient

    assert not issubclass(Transient, QuotaExceeded)
    assert not issubclass(QuotaExceeded, Transient)
