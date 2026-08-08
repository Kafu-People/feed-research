"""M6 units: position-bias correction, signal shape, the exploration slot."""

from __future__ import annotations

from techtrend.personal.learn import SIGNAL, signal_value
from techtrend.personal.rank import Candidate, select_dashboard

# --------------------------------------------------------- position bias


def test_top_skip_outweighs_deep_skip() -> None:
    """A skip at position 1 is a real signal; at position 10 the user
    probably never got there."""
    assert signal_value("skipped", 0, None) < signal_value("skipped", 9, None) < 0


def test_deep_tap_counts_a_little_extra() -> None:
    assert signal_value("tapped_through", 9, None) > signal_value("tapped_through", 0, None) > 0


def test_bounce_dwell_is_negative() -> None:
    assert signal_value("dwell", 0, 2_000) < 0  # sub-5s: a bounce
    assert signal_value("dwell", 0, 60_000) > 0


def test_no_click_signal_exists() -> None:
    """Invariant #8 reaches the learner too: raw clicks teach nothing."""
    assert "click" not in SIGNAL
    assert signal_value("click", 0, None) == 0.0


# ------------------------------------------------------- exploration slot


def _c(story_id: int, score: float, mult: float) -> Candidate:
    from datetime import UTC, datetime

    c = Candidate(
        story_id=story_id,
        headline=f"h{story_id}",
        summary=None,
        source_name="S",
        source_id=1,
        source_count=1,
        published_at=datetime.now(UTC),
        image_url=None,
        url="https://x",
        importance=0.5,
        match_score=0.8,
        topic_id=1,
        topic_label="T",
    )
    c.score = score
    c.personal_mult = mult
    return c


def test_exploration_slot_breaks_the_bubble() -> None:
    """The best card the user's own profile did NOT boost gets the last slot,
    even though pure score ordering would exclude it."""
    boosted = [_c(i, score=1.0 - i / 100, mult=2.0) for i in range(10)]
    outside = _c(99, score=0.2, mult=0.8)  # outside the learned bubble
    out = select_dashboard([*boosted, outside], limit=5, slots=1)
    assert len(out) == 5
    assert out[-1].story_id == 99
    assert out[-1].exploration is True


def test_exploration_is_not_tunable_to_zero() -> None:
    """The slot is the only thing breaking ranker-trains-on-its-own-output.
    slots=0 still reserves one: the outside candidate appears anyway."""
    boosted = [_c(i, score=1.0 - i / 100, mult=2.0) for i in range(10)]
    outside = _c(99, score=0.2, mult=0.9)
    out = select_dashboard([*boosted, outside], limit=5, slots=0)
    assert len(out) == 5
    assert any(c.story_id == 99 and c.exploration for c in out)


def test_short_day_stays_short_with_exploration() -> None:
    """Invariant #10 composes: three cards means three cards."""
    cards = [_c(i, score=1.0, mult=1.0) for i in range(3)]
    assert len(select_dashboard(cards, limit=12, slots=1)) == 3
