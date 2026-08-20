"""Shared value objects. No domain logic."""

from __future__ import annotations

from enum import StrEnum


class Tier(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Stage(StrEnum):
    COLLECT = "collect"
    READ = "read"
    GROUP = "group"
    JUDGE = "judge"
    MATCH = "match"
    FEEDBACK = "feedback"
    NOTIFY = "notify"
    MAINTENANCE = "maintenance"


# Priorities: lower runs first.
PRIORITY_BREAKING = 10
PRIORITY_TIER_AB = 50
PRIORITY_DEFAULT = 100
PRIORITY_BACKFILL = 200
