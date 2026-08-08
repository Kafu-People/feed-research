"""Ranking: the scoring formula, then three rules.

Importance is absolute and precomputed on the story -- identical for every user.
Only the last factor differs per user, which is exactly the promise of the three
layers: the same story looks the same to everyone; only the ordering differs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from techtrend.platform.config import settings

# Freshness decays at different speeds by subject. A markets story is stale in
# hours; a research result is fine three days later. One global half-life is
# wrong for both.
HALF_LIFE_HOURS: dict[str, float] = {
    "markets": 6.0,
    "politics": 18.0,
    "tech": 24.0,
    "research": 72.0,
    "default": 24.0,
}

# Our editorial judgment, baked into the starting position for a new user.
# Original reporting outranks roundups; speculation ranks lowest.
DEFAULT_TYPE_WEIGHT: dict[str, float] = {
    "original_reporting": 0.15,
    "official_announcement": 0.10,
    "analysis": 0.0,
    "rewrite": -0.10,
    "roundup": -0.15,
    "routine_data": -0.10,
    "speculation": -0.20,
}


@dataclass
class Candidate:
    story_id: int
    headline: str
    summary: str | None
    source_name: str
    source_id: int
    source_count: int
    published_at: datetime
    image_url: str | None
    url: str
    importance: float
    match_score: float
    topic_id: int
    topic_label: str
    description: str | None = None
    matched_by: list[str] = field(default_factory=list)
    subject: str = "default"
    story_type: str = "analysis"
    score: float = 0.0
    topic_labels: list[str] = field(default_factory=list)
    personal_mult: float = 1.0
    exploration: bool = False


@dataclass
class Weights:
    by_type: dict[str, float] = field(default_factory=dict)
    by_source: dict[str, float] = field(default_factory=dict)
    by_keyword: dict[str, float] = field(default_factory=dict)

    def multiplier(self, c: Candidate) -> float:
        w = self.by_type.get(c.story_type, DEFAULT_TYPE_WEIGHT.get(c.story_type, 0.0))
        w += self.by_source.get(c.source_name, 0.0)
        w += sum(self.by_keyword.get(k, 0.0) for k in c.matched_by)
        # Bounded so one strong preference can't dominate importance entirely.
        return max(0.25, min(2.5, 1.0 + w))


def freshness(c: Candidate, now: datetime) -> float:
    hours = max(0.0, (now - c.published_at).total_seconds() / 3600.0)
    half_life = HALF_LIFE_HOURS.get(c.subject, HALF_LIFE_HOURS["default"])
    return math.exp(-hours / half_life * math.log(2))


def dedupe_by_story(cards: list[Candidate]) -> list[Candidate]:
    """Invariant #6: one story appears once, at its best score, labelled with
    every topic that matched it. There is no second place for it to show up."""
    best: dict[int, Candidate] = {}
    for c in cards:
        prev = best.get(c.story_id)
        if prev is None:
            c.topic_labels = [c.topic_label]
            best[c.story_id] = c
        else:
            if c.topic_label not in prev.topic_labels:
                prev.topic_labels.append(c.topic_label)
            prev.matched_by = list(dict.fromkeys(prev.matched_by + c.matched_by))
            if c.score > prev.score:
                c.topic_labels = prev.topic_labels
                c.matched_by = prev.matched_by
                best[c.story_id] = c
    return sorted(best.values(), key=lambda x: x.score, reverse=True)


def apply_caps(cards: list[Candidate], per_topic: int, per_source: int) -> list[Candidate]:
    """Invariant #9: diversity caps are hard rules, not scores.

    Applied AFTER sorting, as a filter. A cap expressed as a penalty is a cap a
    sufficiently high score defeats -- which means it isn't a cap.
    """
    topic_seen: dict[int, int] = {}
    source_seen: dict[int, int] = {}
    out: list[Candidate] = []
    for c in cards:
        if topic_seen.get(c.topic_id, 0) >= per_topic:
            continue
        if source_seen.get(c.source_id, 0) >= per_source:
            continue
        topic_seen[c.topic_id] = topic_seen.get(c.topic_id, 0) + 1
        source_seen[c.source_id] = source_seen.get(c.source_id, 0) + 1
        out.append(c)
    return out


def rank(cards: list[Candidate], weights: Weights, now: datetime | None = None) -> list[Candidate]:
    """Score, dedupe, cap. Then stop.

    There is deliberately NO backfill branch. A quiet day is allowed to be
    quiet (invariant #10) -- and that is what keeps every skip a clean negative.
    """
    now = now or datetime.now(UTC)
    s = settings()
    for c in cards:
        c.personal_mult = weights.multiplier(c)
        c.score = c.importance * c.match_score * freshness(c, now) * c.personal_mult
    ordered = dedupe_by_story(cards)
    return apply_caps(ordered, s.cap_per_topic, s.cap_per_source)


def select_dashboard(ranked: list[Candidate], limit: int, slots: int) -> list[Candidate]:
    """The day's cards, with the exploration slot(s) reserved.

    The exploration slot is the ONLY thing breaking the loop where the ranker
    trains on its own output: it shows the best card the user's own learned
    profile would NOT have favoured. `max(1, slots)` is deliberate -- the slot
    is not tunable to zero, and pressure to remove it is the signal it works.
    """
    slots = max(1, slots)
    take = max(0, limit - slots)
    chosen = ranked[:take]
    chosen_ids = {c.story_id for c in chosen}
    rest = [c for c in ranked[take:] if c.story_id not in chosen_ids]

    picks: list[Candidate] = []
    # Best candidates the personal profile did NOT boost: outside the bubble.
    outside = [c for c in rest if c.personal_mult <= 1.0]
    for c in outside[:slots]:
        c.exploration = True
        picks.append(c)
    # A young profile boosts everything or nothing -- fall back to next-best
    # rather than shipping a short day for the wrong reason.
    for c in rest:
        if len(picks) >= slots:
            break
        if c not in picks:
            picks.append(c)
    return chosen + picks


def is_stale(c: Candidate, now: datetime, max_age: timedelta = timedelta(days=3)) -> bool:
    return (now - c.published_at) > max_age
