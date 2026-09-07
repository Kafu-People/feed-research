"""Regression guards on invariants that are currently enforced by an ABSENCE.

These look trivial and are not: if someone adds a `text` field to CardOut in six
months, the failing test explains why they shouldn't.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from techtrend.api.schemas import CardOut, EventKindIn
from techtrend.personal.models import EventKind
from techtrend.personal.rank import Candidate, Weights, apply_caps, dedupe_by_story, rank
from techtrend.platform.config import AI_MODEL_FIELDS, Settings
from techtrend.topic.fingerprint import fingerprint


def _c(**kw: object) -> Candidate:
    base = dict(
        story_id=1,
        headline="h",
        summary="s",
        source_name="Reuters",
        source_id=1,
        source_count=3,
        published_at=datetime.now(UTC),
        image_url=None,
        url="https://x",
        importance=0.5,
        match_score=0.8,
        topic_id=1,
        topic_label="AI chips",
    )
    base.update(kw)
    return Candidate(**base)  # type: ignore[arg-type]


# --------------------------------------------------- #1 never the article body


def test_card_schema_cannot_carry_a_body() -> None:
    fields = set(CardOut.model_fields)
    assert "text" not in fields
    assert "body" not in fields
    assert "content" not in fields


# ------------------------------------------------------- #8 never raw clicks


def test_event_kind_has_no_click() -> None:
    assert "click" not in {e.value for e in EventKind}
    assert "click" not in {e.value for e in EventKindIn}


def test_event_enums_agree() -> None:
    """The API enum and the storage enum must not drift apart."""
    assert {e.value for e in EventKind} == {e.value for e in EventKindIn}


# ------------------------------------------------------------ #6 one story once


def test_one_story_appears_once_with_both_labels() -> None:
    a = _c(story_id=7, topic_id=1, topic_label="AI chips", matched_by=["h100"])
    a.score = 0.4
    b = _c(story_id=7, topic_id=2, topic_label="Export controls", matched_by=["bis"])
    b.score = 0.9
    out = dedupe_by_story([a, b])
    assert len(out) == 1
    assert out[0].score == 0.9  # kept at its BEST score
    assert set(out[0].topic_labels) == {"AI chips", "Export controls"}
    assert set(out[0].matched_by) == {"h100", "bis"}


# ------------------------------------------------------ #9 caps are hard rules


def test_caps_drop_cards_and_never_rescore() -> None:
    cards = []
    for i, s in enumerate([0.9, 0.8, 0.7, 0.6]):
        c = _c(story_id=i, topic_id=1, source_id=1)
        c.score = s
        cards.append(c)
    out = apply_caps(cards, per_topic=3, per_source=99)
    assert len(out) == 3
    assert [c.score for c in out] == [0.9, 0.8, 0.7]  # untouched, not penalised


def test_source_cap_is_independent_of_topic_cap() -> None:
    cards = []
    for i in range(5):
        c = _c(story_id=i, topic_id=i, source_id=1)  # 5 topics, 1 source
        c.score = 1.0 - i / 10
        cards.append(c)
    assert len(apply_caps(cards, per_topic=99, per_source=2)) == 2


# ------------------------------------------------------------ #10 never pad


def test_short_day_stays_short() -> None:
    cards = [_c(story_id=i, topic_id=i, source_id=i) for i in range(7)]
    out = rank(cards, Weights())
    assert len(out) == 7  # seven good things -> seven cards, no backfill


def test_there_is_no_minimum_cards_setting() -> None:
    """Invariant #10 is enforced by the ABSENCE of a floor."""
    assert not any("min_cards" in f for f in Settings.model_fields)


# --------------------------------------- politeness ceiling is in the type


@pytest.mark.parametrize("value", [0, 3, 32])
def test_per_host_concurrency_is_bounded_by_the_type(value: int) -> None:
    """One or two connections per site, never more. An over-eager setting is a
    STARTUP FAILURE, not a publisher complaint."""
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        Settings(per_host_concurrency=value, jwt_secret="x")  # type: ignore[arg-type]


# ------------------------------------------------------------- ranking shape


def test_importance_is_absolute_across_topics() -> None:
    """A big development in a minor topic outranks a routine story in a major one."""
    big_minor = _c(story_id=1, topic_id=9, importance=0.95, match_score=0.6)
    routine_major = _c(story_id=2, topic_id=1, importance=0.20, match_score=1.0)
    out = rank([routine_major, big_minor], Weights())
    assert out[0].story_id == 1


def test_freshness_decays_faster_for_markets_than_research() -> None:
    now = datetime.now(UTC)
    old = now - timedelta(hours=12)
    mkt = _c(story_id=1, subject="markets", published_at=old)
    res = _c(story_id=2, subject="research", published_at=old)
    out = rank([mkt, res], Weights(), now=now)
    assert out[0].story_id == 2


# --------------------------------------------------------- topic dedup


def test_fingerprint_ignores_order_case_and_punctuation() -> None:
    a = fingerprint(["AI chip", "GPU"], ["tariff"], ["Nvidia"], [])
    b = fingerprint(["gpu", "ai-chip!"], ["Tariff"], ["nvidia"], [])
    assert a == b


def test_fingerprint_separates_different_topics() -> None:
    a = fingerprint(["AI chip"], [], [], [])
    b = fingerprint(["AI chip"], [], [], ["gaming"])
    assert a != b


# --------------------------------------------------- South Korea, 2026-09-07


def test_south_korea_is_blocked() -> None:
    from techtrend.platform.config import settings
    from techtrend.topic.match import blocked, searchable

    terms = settings().block_terms
    for title in (
        "South Korea targets a 2030 Moon landing",
        "New South Korean 'fake news' law alarms US lawmakers",
        "SK Hynix to invest $38 billion building memory chip plants",
        "Save $800 on the LG 65-inch Gallery TV",
    ):
        assert blocked(searchable(title, None, []), terms) is not None, title


def test_north_korea_survives_the_south_korea_ban() -> None:
    """A different country. The bare terms "korea"/"korean" are deliberately
    absent so Lazarus and IT-worker security reporting keeps flowing."""
    from techtrend.platform.config import settings
    from techtrend.topic.match import blocked, searchable

    terms = settings().block_terms
    for title in (
        "North Korean hackers exploited a Windows zero-day",
        "North Korean remote IT staffer worked for a US agency, says FBI",
    ):
        assert blocked(searchable(title, None, []), terms) is None, title


def test_samsung_survives_the_south_korea_ban() -> None:
    """Kept by explicit operator choice: a Korean company, but the coverage is
    global phone and chip news rather than a South Korea story."""
    from techtrend.platform.config import settings
    from techtrend.topic.match import blocked, searchable

    terms = settings().block_terms
    assert blocked(searchable("Samsung Galaxy S27 Ultra camera leak", None, []), terms) is None


# ---------------------------------------------- the model ban (2026-09-07)
#
# Two standing operator rules: summaries run on Haiku and nothing else, and no
# stage anywhere runs on Opus. Defaults already satisfied both -- these pin
# that an env var cannot quietly undo them, which is the only way they break.


def test_opus_is_refused_for_every_ai_stage() -> None:
    for field in AI_MODEL_FIELDS:
        with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
            Settings(**{field: "claude-opus-5"})


def test_the_ban_is_on_the_family_not_one_model_id() -> None:
    """A new Opus release must not walk around a pinned string."""
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        Settings(ai_model="claude-opus-4-8")


def test_summaries_refuse_anything_that_is_not_haiku() -> None:
    """Sonnet is not Opus, and is still not allowed to write summaries."""
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        Settings(ai_summary_model="claude-sonnet-5")


def test_every_ai_model_field_is_covered_by_the_guard() -> None:
    """The guard reads a hand-written tuple. A model setting added later and
    left out of it would be silently unguarded."""
    declared = {f for f in Settings.model_fields if f.startswith("ai_") and f.endswith("_model")}
    assert declared == set(AI_MODEL_FIELDS)


def test_the_defaults_already_satisfy_the_ban() -> None:
    s = Settings()
    for field in AI_MODEL_FIELDS:
        assert "haiku" in getattr(s, field).lower(), field
