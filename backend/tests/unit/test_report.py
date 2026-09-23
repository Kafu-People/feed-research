"""Weekly roundup units: the week boundary, and the gate in front of the model.

The two things that can actually go wrong are a timezone bug in the window
(which silently summarises the wrong seven days) and a gate that stops firing.
The gate matters more here than anywhere else: this surface hands headlines to
a model that writes prose, so a blocked story that reaches the prompt can come
back out as a sentence no later check is reading.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from techtrend.deliver import report as R

SP = ZoneInfo("America/Sao_Paulo")


def _utc(y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def _row(
    title: str,
    domain: str = "example.com",
    desc: str | None = None,
    day: int = 2,
    outlets: int = 3,
) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        description=desc,
        entities=[],
        site="Test Site",
        domain=domain,
        posted_at=_utc(2026, 9, day, 12),
        ts=f"178{day}.0001",
        source_count=outlets,
        topics="AI models & labs",
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
    """A Tuesday re-run after an outage must reproduce Saturday's roundup, not
    invent a window ending on Tuesday."""
    _, until = R.week_window(_utc(2026, 9, 8, 10, 0))
    assert until.astimezone(SP).date().isoformat() == "2026-09-05"


def test_window_is_stable_across_the_whole_week() -> None:
    base = R.week_window(_utc(2026, 9, 5, 18, 1))
    for day, hour in ((6, 3), (7, 12), (9, 23), (11, 6), (12, 17)):
        assert R.week_window(_utc(2026, 9, day, hour)) == base


# ---------------------------------------------- the gate, before the model


def test_term_gate_blocks_a_banned_subject() -> None:
    kept, dropped = R.gate([_row("Netanyahu meets tech leaders in Tel Aviv")])
    assert (kept, dropped) == ([], 1)


def test_term_gate_blocks_trump() -> None:
    kept, dropped = R.gate([_row("Trump announces a new tariff on chips")])
    assert (kept, dropped) == ([], 1)


def test_site_gate_blocks_a_banned_publisher_subdomain() -> None:
    """A ban a subdomain walks around is not a ban."""
    kept, dropped = R.gate([_row("An ordinary story", domain="news.bbc.co.uk")])
    assert (kept, dropped) == ([], 1)


def test_gate_reads_the_description_not_only_the_title() -> None:
    kept, dropped = R.gate([_row("A neutral headline", desc="Reporting from Gaza today.")])
    assert (kept, dropped) == ([], 1)


def test_clean_story_survives_both_gates() -> None:
    kept, dropped = R.gate([_row("Apple ships a new laptop", domain="theverge.com")])
    assert dropped == 0
    assert [k.title for k in kept] == ["Apple ships a new laptop"]


def test_blocked_story_never_reaches_the_prompt() -> None:
    """The prompt is the thing that matters: whatever the gate drops must not
    appear in the text handed to the model."""
    rows, _ = R.gate([_row("Trump on chips"), _row("Apple ships a new laptop")])
    prompt = R.render_headlines(rows)
    assert "Trump" not in prompt
    assert "Apple ships a new laptop" in prompt


# ------------------------------------------------------- the model's input


def test_headlines_are_numbered_from_one() -> None:
    """The model links by index, so the first story must be 1."""
    prompt = R.render_headlines([_row("First"), _row("Second")])
    assert prompt.startswith("1. ")
    assert "\n2. " in prompt


def test_headlines_carry_the_day() -> None:
    """A week's arc is invisible if the list never says which day a story ran."""
    prompt = R.render_headlines([_row("A story", day=2)])  # 2026-09-02 is a Wednesday
    assert "(Wed)" in prompt


def test_headlines_carry_reach_only_when_it_is_plural() -> None:
    assert "9 outlets" in R.render_headlines([_row("Big", outlets=9)])
    assert "outlets" not in R.render_headlines([_row("Small", outlets=1)])


# ------------------------------------------------------------- the blocks


def test_body_over_the_slack_section_limit_is_split_not_truncated() -> None:
    body = "\n\n".join(["x" * 1000] * 6)
    _, blocks = R.blocks_for(_utc(2026, 9, 5, 18), body, 231, 40)
    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) > 1
    assert all(len(b["text"]["text"]) <= 3000 for b in sections)
    assert sum(len(b["text"]["text"].replace("\n", "")) for b in sections) == len(
        body.replace("\n", "")
    )


# ------------------------------------------------- the gate on the OUTPUT


def test_output_gate_catches_a_banned_subject_the_model_invented() -> None:
    """The input gate cannot protect a surface that writes. The model can name
    a banned subject from its own knowledge with no story behind it, so the
    prose is checked before it is filed."""
    from techtrend.platform.config import settings
    from techtrend.topic.match import blocked, searchable

    prose = "• Chip export rules tightened. Israel expanded its own fab programme."
    assert blocked(searchable(prose, None, []), settings().block_terms) == "israel"


def test_output_gate_passes_clean_prose() -> None:
    from techtrend.platform.config import settings
    from techtrend.topic.match import blocked, searchable

    prose = "• Apple shipped a laptop. Nvidia bought a startup. Prices fell."
    assert blocked(searchable(prose, None, []), settings().block_terms) is None
