"""Adaptive check intervals. The schedule IS the `next_check_at` column.

A site that publishes on every check converges to its tier's base interval;
a site quiet three checks running backs off toward the tier cap. Failures
back off exponentially, and ten in a row parks the endpoint (it leaves the
partial index of due rows until a human or the coverage audit revives it).
"""

from __future__ import annotations

from dataclasses import dataclass

TIER_BASE_S = {"A": 120, "B": 600, "C": 2700}
_BACKOFF_AFTER_QUIET = 3
_QUIET_FACTOR = 1.5
_MAX_MULT = 8  # cap: 8x the tier base
_FAILURE_CAP_S = 6 * 3600
PARKED_FAILURE_STREAK = 10  # matches the partial-index predicate on endpoints


@dataclass(frozen=True)
class Next:
    interval_s: int
    quiet_streak: int
    failure_streak: int


def after_check(tier: str, interval_s: int, quiet_streak: int, *, published: bool) -> Next:
    """A successful check: speed up on news, back off on silence."""
    base = TIER_BASE_S.get(tier, TIER_BASE_S["C"])
    if published:
        # Halve toward the base but never below it -- politeness has a floor.
        return Next(max(base, interval_s // 2), 0, 0)
    quiet = quiet_streak + 1
    if quiet >= _BACKOFF_AFTER_QUIET:
        return Next(min(base * _MAX_MULT, int(interval_s * _QUIET_FACTOR)), quiet, 0)
    return Next(interval_s, quiet, 0)


def after_failure(tier: str, interval_s: int, failure_streak: int) -> Next:
    """A failed check: exponential backoff, capped; streak 10 parks the endpoint."""
    streak = failure_streak + 1
    return Next(min(_FAILURE_CAP_S, max(interval_s, 60) * 2), 0, streak)
