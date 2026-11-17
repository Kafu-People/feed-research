"""#feed-ai-news editions: format, schedule, ranking, posting, digest links,
the Friday roundup and reaction feedback."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from techtrend.deliver import news_format as nf
from techtrend.deliver import reactions as rx
from techtrend.deliver.brief import slack_problems


@dataclass
class Row:
    id: int
    title: str
    url: str = "https://example.com/a"
    site: str = "TechCrunch"
    source_count: int = 1
    importance: float = 0.5
    description: str | None = None
    site_id: int = 1
    text_key: str | None = None
    topic_titles: list[str] = field(default_factory=lambda: ["AI models & labs"])


# ------------------------------------------------------------- categories


@pytest.mark.parametrize(
    ("title", "emoji"),
    [
        ("Voyage Labs raises $12 million for an AI travel assistant", "💰"),
        ("California sues OpenAI over autonomous hacking", "⚖️"),
        ("Google warns fully automated attacks are near", "🔐"),
        ("Mercor opens 239 red-team contractor roles", "🔐"),
        ("Data annotation workers report pay cuts", "💼"),
        ("Google AI Mode gets temporary threads", "🧠"),
        ("Chrome extension adds a Gemini sidebar", "🔧"),
        ("Apple's new study looks to improve AI health tools", "🧠"),  # not "app"
        # Both filed under 🧠 in the 2026-11-17 dry run.
        ("The Department of Justice Is Using AI Detector Pangram Against Defense Attorneys", "⚖️"),
        ("AI safety legislation has a conflict-of-interest problem", "⚖️"),
    ],
)
def test_category_comes_from_the_storys_own_words(title: str, emoji: str) -> None:
    assert nf.category(title)[0] == emoji


def test_three_outlets_is_flagged_whatever_the_subject() -> None:
    assert nf.category("Voyage Labs raises $12M", outlets=3)[0] == "🔥"


def test_blurb_is_the_first_sentence_and_short() -> None:
    s = "Voyage Labs raised $12 million to build Atlas. Unlike general tools, it stays."
    assert nf.blurb(s) == "Voyage Labs raised $12 million to build Atlas."
    long = "word " * 80 + "end."
    assert len(nf.blurb(long)) <= nf.BLURB_MAX and nf.blurb(long).endswith("…")
    assert nf.blurb(None, "Publisher description.") == "Publisher description."
    assert "`" not in nf.blurb("`Voyage Labs` raised `$12 million`.")


# ----------------------------------------------------------------- blocks


def test_edition_shows_the_top_stories_and_points_to_the_thread() -> None:
    rows = [Row(i, f"Story {i} raises $1M", source_count=1 + (i == 0) * 3) for i in range(11)]
    fallback, blocks = nf.edition_blocks(
        name="Midday", when="Tue Nov 17", rows=rows, summaries={0: "It happened. More."}, top=8
    )
    assert slack_problems(blocks) == []
    assert blocks[0]["text"]["text"] == "📰 AI News — Midday · Tue Nov 17 (11 stories)"
    body = "\n".join(b["text"]["text"] for b in blocks if b["type"] == "section")
    assert body.count("<https://example.com/a|") == 8
    assert "🔥" in body and "— 4 outlets" in body and "It happened." in body
    assert "More." not in body  # only the blurb in the channel
    footer = blocks[-1]["elements"][0]["text"]
    assert footer.startswith("+3 more · full summaries in the thread")
    assert "👍" in footer and fallback.startswith("📰 AI News — Midday")


def test_a_big_edition_stays_within_slack_limits() -> None:
    rows = [Row(i, "A long headline " * 12, description="d " * 200) for i in range(60)]
    _, blocks = nf.edition_blocks(name="Morning", when="Wed", rows=rows, summaries={}, top=60)
    assert slack_problems(blocks) == []


def test_reply_carries_the_full_summary_and_escapes_titles() -> None:
    _, blocks = nf.story_reply_blocks(Row(1, "R&D <up> | down", source_count=2), "Full. Summary.")
    t = blocks[0]["text"]["text"]
    assert "Full. Summary." in t and "· 2 outlets ·" in t
    assert "R&D &lt;up&gt; ❘ down" in t
    assert slack_problems(blocks) == []


# --------------------------------------------------------------- schedule


class _S:
    edition_hours = [8, 12, 15]
    edition_timezone = "America/New_York"
    slack_delivery_mode = "editions"


@pytest.mark.parametrize(
    ("utc", "key", "name", "since"),
    [
        # 08:30 New York = 13:30 UTC; the morning window starts at 14:00 NY yesterday.
        (
            datetime(2026, 11, 17, 13, 30, tzinfo=UTC),
            "edition:2026-11-17:08",
            "Morning",
            "2026-11-16T19:00:00+00:00",
        ),
        (
            datetime(2026, 11, 17, 17, 5, tzinfo=UTC),
            "edition:2026-11-17:12",
            "Midday",
            "2026-11-17T12:00:00+00:00",
        ),
        # 23:00 New York: only the latest edition, not all three.
        (
            datetime(2026, 11, 18, 4, 0, tzinfo=UTC),
            "edition:2026-11-17:15",
            "Afternoon",
            "2026-11-17T16:00:00+00:00",
        ),
    ],
)
def test_the_latest_due_edition_is_queued(
    monkeypatch: pytest.MonkeyPatch, utc: datetime, key: str, name: str, since: str
) -> None:
    from techtrend import cli

    monkeypatch.setattr(cli, "settings", lambda: _S())
    got_key, payload = cli.edition_due(utc)  # type: ignore[misc]
    assert got_key == key and payload["edition"] == name and payload["since"] == since


def test_no_edition_before_the_first_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    from techtrend import cli

    monkeypatch.setattr(cli, "settings", lambda: _S())
    assert cli.edition_due(datetime(2026, 11, 17, 11, 0, tzinfo=UTC)) is None  # 06:00 NY


# ---------------------------------------------------------------- ranking


def test_rank_uses_importance_reach_and_feedback() -> None:
    from techtrend.deliver.hourly import rank

    a = Row(1, "Model update", importance=0.60)
    b = Row(2, "Startup raises $5M", importance=0.55, source_count=3)  # +0.10 reach
    c = Row(3, "Another model", importance=0.62, site_id=9)
    assert [r.id for r in rank([a, b, c], {}, {})] == [2, 3, 1]
    # The team keeps 👎-ing publisher 9: it drops, but stays in the list.
    assert [r.id for r in rank([a, b, c], {}, {9: -0.15})] == [2, 1, 3]


# ---------------------------------------------------------- the edition job


class _Spy:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

    async def post(self, channel, text_, blocks=None, thread_ts=None, unfurl=True):
        self.posts.append({"text": text_, "blocks": blocks or [], "thread_ts": thread_ts})
        return f"ts{len(self.posts)}"


def _wire(monkeypatch: pytest.MonkeyPatch, rows: list[Row]) -> tuple[_Spy, list[dict]]:
    from techtrend.deliver import hourly

    recorded: list[dict] = []

    class _Session:
        async def execute(self, stmt, params=None):
            if params and "reply" in params:
                recorded.append(params)

    @contextlib.asynccontextmanager
    async def scope():
        yield _Session()

    async def window(since, until, cap, floor_for):
        return rows

    async def summaries(rows_, *, since, until, extra=None):
        return {r.id: f"Summary of {r.id}. Second sentence." for r in rows_}

    async def no_boosts():
        return {}, {}

    class _Cfg:
        edition_channel_top = 2
        breaking_min_outlets = 4
        breaking_min_importance = 0.7
        slack_summaries = False

    spy = _Spy()
    monkeypatch.setattr(hourly, "session_scope", scope)
    monkeypatch.setattr(hourly, "_window", window)
    monkeypatch.setattr(hourly, "_summaries", summaries)
    monkeypatch.setattr(hourly, "SlackClient", lambda: spy)
    monkeypatch.setattr(hourly, "settings", lambda: _Cfg())
    monkeypatch.setattr(rx, "boosts", no_boosts)
    return spy, recorded


@pytest.mark.asyncio
async def test_an_edition_posts_once_and_threads_every_story(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from techtrend.deliver import hourly

    rows = [Row(1, "Low", importance=0.3), Row(2, "High", importance=0.9), Row(3, "Mid")]
    spy, recorded = _wire(monkeypatch, rows)
    payload = {"edition": "Midday", "when": "Tue Nov 17", "since": "2026-11-17T12:00:00+00:00"}
    await hourly._edition(payload, "C0NEWS")
    top = [p for p in spy.posts if p["thread_ts"] is None]
    replies = [p for p in spy.posts if p["thread_ts"] == "ts1"]
    assert len(top) == 1 and len(replies) == 3  # everything posted, one reply each
    assert [p["text"] for p in replies] == ["High", "Mid", "Low"]  # ranked
    assert "+1 more" in str(top[0]["blocks"])
    # Each story recorded against the edition, with its own reply as summary_ts.
    assert [(r["id"], r["ts"], r["reply"]) for r in recorded] == [
        (2, "ts1", "ts2"),
        (3, "ts1", "ts3"),
        (1, "ts1", "ts4"),
    ]


@pytest.mark.asyncio
async def test_breaking_posts_only_wide_important_stories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from techtrend.deliver import hourly

    rows = [
        Row(1, "Wide and important", source_count=5, importance=0.8),
        Row(2, "Wide, minor", source_count=6, importance=0.4),
        Row(3, "Important, narrow", source_count=1, importance=0.9),
    ]
    spy, recorded = _wire(monkeypatch, rows)
    await hourly._breaking("C0NEWS")
    top = [p for p in spy.posts if p["thread_ts"] is None]
    assert len(top) == 1 and top[0]["text"].startswith("⚡ Breaking — 5 outlets")
    assert [r["id"] for r in recorded] == [1]  # recorded, so no edition repeats it


# ------------------------------------------------------------- the digest


@pytest.mark.asyncio
async def test_digest_links_go_to_the_article_and_leave_no_raw_refs() -> None:
    from techtrend.deliver.digest import linkify

    @dataclass
    class D:
        url: str | None
        ts: str = "1.0"

    class _C:
        async def permalink(self, channel, ts):
            return "https://slack/permalink"

    long_phrase = "Claude's new Mythos version can write GPU software kernels " * 3
    body = f"[Anthropic IPO](1) and [{long_phrase.strip()}](2). [Invented](9). [No url](3)."
    rows = [D("https://ft.com/ipo"), D("https://x.com/mythos"), D(None)]
    out = await linkify(body, rows, _C(), "C0")  # type: ignore[arg-type]
    assert "<https://ft.com/ipo|Anthropic IPO>" in out
    assert "<https://x.com/mythos|Claude's new Mythos" in out
    assert "<https://slack/permalink|No url>" in out
    assert "Invented" in out and "(9)" not in out and "](" not in out


@pytest.mark.asyncio
async def test_the_weekly_kind_rides_the_digest_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    from techtrend.deliver import digest, report

    called: list[str] = []

    async def fake_run(job):
        called.append("weekly")

    monkeypatch.setattr(report, "run", fake_run)

    @dataclass
    class J:
        payload: dict

    await digest.run(J({"kind": "weekly", "day": "2026-11-20"}))  # type: ignore[arg-type]
    assert called == ["weekly"]


# -------------------------------------------------------------- reactions


@pytest.mark.parametrize(
    ("name", "vote"),
    [
        ("+1", 1),
        ("thumbsup", 1),
        ("+1::skin-tone-3", 1),
        ("-1", -1),
        ("thumbsdown", -1),
        ("heart", 0),
        ("eyes", 0),
    ],
)
def test_only_thumbs_count(name: str, vote: int) -> None:
    assert rx.vote_for(name) == vote


def test_feedback_boost_is_capped() -> None:
    r = Row(1, "Startup raises $5M", site_id=7)
    assert rx.boost_for(r, {"funding": 0.15}, {7: 0.15}) == rx.CAP
    assert rx.boost_for(r, {"funding": -0.15}, {7: -0.15}) == -rx.CAP
    assert rx.boost_for(r, {}, {}) == 0.0


@pytest.mark.asyncio
async def test_a_reaction_is_recorded_against_its_story(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: list[tuple[str, dict]] = []

    @dataclass
    class StoryRow:
        id: int = 42
        title: str = "Startup raises $5M"
        description: str | None = None
        site_id: int = 7
        source_count: int = 1

    class _Result:
        def __init__(self, row):
            self.row = row

        def first(self):
            return self.row

    class _Session:
        async def execute(self, stmt, params=None):
            executed.append((str(stmt).split()[0], params or {}))
            return _Result(StoryRow() if params and params.get("ts") == "reply1" else None)

    @contextlib.asynccontextmanager
    async def scope():
        yield _Session()

    class _Cfg:
        slack_channel = "C0NEWS"

    monkeypatch.setattr(rx, "session_scope", scope)
    monkeypatch.setattr(rx, "settings", lambda: _Cfg())
    ev = {
        "type": "reaction_added",
        "reaction": "+1",
        "user": "U1",
        "item": {"type": "message", "channel": "C0NEWS", "ts": "reply1"},
    }
    assert await rx.handle(ev)
    insert = executed[-1]
    assert insert[0] == "INSERT" and insert[1]["vote"] == 1 and insert[1]["cat"] == "funding"

    assert await rx.handle({**ev, "type": "reaction_removed"})
    assert executed[-1][0] == "DELETE"

    # Not a story reply, another channel, or an emoji we do not count: ignored.
    assert not await rx.handle({**ev, "item": {**ev["item"], "ts": "edition-header"}})
    assert not await rx.handle({**ev, "item": {**ev["item"], "channel": "C0OTHER"}})
    assert not await rx.handle({**ev, "reaction": "heart"})
