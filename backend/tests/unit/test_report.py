"""Weekly report units: the week boundary, and the gates on what it surfaces.

The two things that can actually go wrong here are a timezone bug in the
window (which silently reports the wrong seven days) and a gate that stops
firing (which puts banned content in front of a reader). Both are pinned with
real instants in a real zone rather than a mocked clock.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from techtrend.deliver import report as R

SP = ZoneInfo("America/Sao_Paulo")


def _utc(y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def _row(title: str, domain: str = "example.com", desc: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        description=desc,
        entities=[],
        site="Test Site",
        domain=domain,
        source_count=3,
        importance=0.5,
    )


# ----------------------------------------------------------- the window


def test_window_is_a_full_seven_days() -> None:
    since, until = R.week_window(_utc(2026, 9, 5, 20, 16))
    assert (until - since).days == 7


def test_window_ends_saturday_at_the_report_hour_local() -> None:
    _, until = R.week_window(_utc(2026, 9, 5, 20, 16))  # Sat 17:16 local
    local = until.astimezone(SP)
    assert local.weekday() == R.REPORT_WEEKDAY
    assert (local.hour, local.minute) == (R.REPORT_HOUR, 0)


def test_saturday_before_the_hour_reports_the_previous_week() -> None:
    """At 14:00 local on Saturday this week is not over, so the completed week
    is the one ending the Saturday before -- not a half-week ending today."""
    _, until = R.week_window(_utc(2026, 9, 5, 17, 0))  # Sat 14:00 local
    assert until.astimezone(SP).date().isoformat() == "2026-08-29"


def test_saturday_after_the_hour_reports_the_week_just_closed() -> None:
    _, until = R.week_window(_utc(2026, 9, 5, 18, 1))  # Sat 15:01 local
    assert until.astimezone(SP).date().isoformat() == "2026-09-05"


def test_midweek_still_reports_the_last_closed_week() -> None:
    """A Tuesday re-run after an outage must reproduce Saturday's report, not
    invent a window ending on Tuesday."""
    _, until = R.week_window(_utc(2026, 9, 8, 10, 0))
    assert until.astimezone(SP).date().isoformat() == "2026-09-05"


def test_window_is_stable_across_the_whole_week() -> None:
    """Every instant between two Saturdays yields the same window."""
    base = R.week_window(_utc(2026, 9, 5, 18, 1))
    for day, hour in ((6, 3), (7, 12), (9, 23), (11, 6), (12, 17)):
        assert R.week_window(_utc(2026, 9, day, hour)) == base


# ------------------------------------------------------------- the gates


def test_term_gate_blocks_a_banned_subject() -> None:
    kept, dropped = R._gated_top([_row("Netanyahu meets tech leaders in Tel Aviv")])
    assert (kept, dropped) == ([], 1)


def test_term_gate_blocks_trump() -> None:
    kept, dropped = R._gated_top([_row("Trump announces a new tariff on chips")])
    assert (kept, dropped) == ([], 1)


def test_site_gate_blocks_a_banned_publisher_subdomain() -> None:
    """A ban a subdomain walks around is not a ban."""
    kept, dropped = R._gated_top([_row("An ordinary story", domain="news.bbc.co.uk")])
    assert (kept, dropped) == ([], 1)


def test_gate_reads_the_description_not_only_the_title() -> None:
    kept, dropped = R._gated_top([_row("A neutral headline", desc="Reporting from Gaza today.")])
    assert (kept, dropped) == ([], 1)


def test_clean_story_survives_both_gates() -> None:
    kept, dropped = R._gated_top([_row("Apple ships a new laptop", domain="theverge.com")])
    assert dropped == 0
    assert [k.title for k in kept] == ["Apple ships a new laptop"]


def test_gating_happens_before_the_cut_not_after() -> None:
    """Blocked rows must not consume slots. Ten clean stories follow one
    blocked story, and all ten have to survive -- gating after the trim would
    return nine and read as a quiet week."""
    rows = [_row("Trump does something")] + [_row(f"Clean story {i}") for i in range(10)]
    kept, dropped = R._gated_top(rows, keep=10)
    assert dropped == 1
    assert len(kept) == 10


def test_keep_limit_is_honoured() -> None:
    kept, _ = R._gated_top([_row(f"Story {i}") for i in range(50)], keep=10)
    assert len(kept) == 10


# -------------------------------------------------- week-over-week honesty


def _topic(created: datetime, n: int, n_prev: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=1, title="T", subscriber_count=1, created_at=created, n=n, n_prev=n_prev, score=0.5
    )


def _topics_table(rows: list[SimpleNamespace]) -> str:
    since, until = R.week_window(_utc(2026, 9, 5, 20, 16))
    r = R.Report(since=since, until=until, topics=rows)
    return R.render(r)


def test_topic_created_inside_the_window_is_not_given_a_percentage() -> None:
    """A topic backfills against the standing corpus on its first pass. Calling
    the drop off that spike '-91%' reports a collapse that never happened."""
    out = _topics_table([_topic(datetime(2026, 8, 24, tzinfo=UTC), 5, 56)])
    assert "backfill*" in out
    assert "-91%" not in out


def test_established_topic_still_gets_its_percentage() -> None:
    out = _topics_table([_topic(datetime(2026, 7, 1, tzinfo=UTC), 1132, 1000)])
    assert "+13%" in out
    assert "backfill*" not in out
