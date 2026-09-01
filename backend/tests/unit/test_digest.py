"""Daily digest units: the schedule, the model's link syntax, and the split.

The scheduling tests pin real instants in a real zone rather than mocking a
clock, because the bug this feature can actually have is a timezone bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from techtrend.deliver import digest as D

SP = ZoneInfo("America/Sao_Paulo")


def _utc(y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


# ------------------------------------------------------------- scheduling


def test_brazil_is_utc_minus_3_year_round() -> None:
    """Brazil abolished DST in 2019. If this ever fails, the offset moved and
    the digest hour silently moved with it."""
    for month in (1, 6, 12):
        assert datetime(2026, month, 15, 18, tzinfo=SP).astimezone(UTC).hour == 21


def test_not_due_before_the_hour() -> None:
    assert not D.is_due(_utc(2026, 9, 1, 20, 59))  # 17:59 local


def test_due_on_the_hour() -> None:
    assert D.is_due(_utc(2026, 9, 1, 21, 0))  # 18:00 local


def test_still_due_after_a_worker_outage() -> None:
    """Down at 18:00, back at 22:40 local -- the day still gets its report."""
    assert D.is_due(_utc(2026, 9, 2, 1, 40))


def test_not_due_again_after_midnight_rolls_the_day() -> None:
    assert not D.is_due(_utc(2026, 9, 2, 4, 0))  # 01:00 local, next day


def test_local_day_is_the_brazil_date_not_the_utc_date() -> None:
    """02:00 UTC on the 1st is still the 31st in Sao Paulo. Keying the ledger
    on the UTC date would file two digests for one local day."""
    assert D.local_day(_utc(2026, 9, 1, 2, 0)).isoformat() == "2026-08-31"


# ------------------------------------------------------------ the model IO


@dataclass
class _Row:
    title: str
    site: str
    source_count: int
    topics: str
    ts: str


def _rows(n: int = 3) -> list[_Row]:
    return [
        _Row(f"Story {i}", "The Verge", i, "AI models & labs", f"178822233{i}.0001")
        for i in range(1, n + 1)
    ]


class _StubSlack:
    def __init__(self, fail: set[int] | None = None) -> None:
        self.fail = fail or set()
        self.calls = 0

    async def permalink(self, channel: str, ts: str) -> str | None:
        self.calls += 1
        n = int(ts.split(".")[0][-1])
        return None if n in self.fail else f"https://slack.test/p{ts.replace('.', '')}"


def test_headlines_are_numbered_from_one() -> None:
    out = D.render_headlines(_rows(2))
    assert out.splitlines()[0].startswith("1. Story 1")
    assert out.splitlines()[1].startswith("2. Story 2")


def test_headlines_mark_multi_outlet_reach() -> None:
    out = D.render_headlines(_rows(2))
    assert "2 outlets" in out.splitlines()[1]
    assert "1 outlets" not in out  # a single outlet is unremarkable, so unsaid


@pytest.mark.asyncio
async def test_linkify_resolves_a_reference() -> None:
    rows, slack = _rows(3), _StubSlack()
    out = await D.linkify("The [EU acted](2) today.", rows, slack, "#c")
    assert out == "The <https://slack.test/p17882223320001|EU acted> today."


@pytest.mark.asyncio
async def test_linkify_resolves_each_number_once() -> None:
    """Two references to one story must not cost two API calls."""
    slack = _StubSlack()
    await D.linkify("[a](1) and [b](1) and [c](2)", _rows(3), slack, "#c")
    assert slack.calls == 2


@pytest.mark.asyncio
async def test_hallucinated_index_degrades_to_plain_text() -> None:
    """The model inventing story 99 must not emit a broken link."""
    out = await D.linkify("See [this](99).", _rows(3), _StubSlack(), "#c")
    assert out == "See this."


@pytest.mark.asyncio
async def test_unresolvable_permalink_degrades_to_plain_text() -> None:
    out = await D.linkify("See [this](2).", _rows(3), _StubSlack(fail={2}), "#c")
    assert out == "See this."


@pytest.mark.asyncio
async def test_a_year_in_parentheses_is_not_a_reference() -> None:
    """'[the ruling] (2026)' must not be read as a link to story 2026."""
    out = await D.linkify("The [ruling] (2026) stands.", _rows(3), _StubSlack(), "#c")
    assert out == "The [ruling] (2026) stands."


@pytest.mark.asyncio
async def test_pipe_in_link_text_cannot_break_the_link() -> None:
    """A raw | would terminate Slack's <url|text> early and mangle the line."""
    out = await D.linkify("[a|b](1) here", _rows(3), _StubSlack(), "#c")
    assert out.count("|") == 1


# --------------------------------------------------------------- chunking


def test_short_body_is_one_chunk() -> None:
    assert D._chunk("short", 2900) == ["short"]


def test_chunking_splits_on_paragraphs_and_loses_nothing() -> None:
    body = "\n\n".join(f"paragraph {i} " + "x" * 400 for i in range(12))
    chunks = D._chunk(body, 1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks).replace("\n", "") == body.replace("\n", "")


def test_blocks_carry_a_header_body_and_context() -> None:
    from datetime import date

    fallback, blocks = D.blocks_for(date(2026, 9, 1), "• a line", 39, 21)
    assert "TechTrend Daily" in fallback
    assert [b["type"] for b in blocks] == ["header", "section", "context"]
    assert "39 stories · 21 sources" in blocks[-1]["elements"][0]["text"]
