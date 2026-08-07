"""The clustering decision. Tuned for PRECISION.

A missed merge shows the same event twice -- annoying. A wrong merge makes
the app lie and silently disappears an event -- unrecoverable. The asymmetry
is not close, so three independent signals must ALL agree:

    similar embedding        the meanings match
    overlapping title words  the surface forms match
    shared named entities    the actors match

Thresholds live in config and are swept by the clustering harness -- never
tune them from a single anecdote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from techtrend.platform.config import settings
from techtrend.shared.read.entities import entity_tokens

_WORD = re.compile(r"[a-z0-9]+")
_TITLE_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "at",
    "by",
    "from",
    "as",
    "is",
    "are",
    "was",
    "be",
    "its",
    "it",
    "this",
    "that",
    "after",
    "over",
    "up",
    "out",
    "new",
    "how",
    "why",
    "what",
}


def title_tokens(title: str) -> set[str]:
    return {w for w in _WORD.findall(title.lower()) if w not in _TITLE_STOP}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True)
class Candidate:
    article_id: int
    story_id: int
    cosine: float  # precomputed by pgvector in the retrieval query
    title: str
    entities: list[str]


def same_event(cand: Candidate, title: str, entities: list[str]) -> bool:
    s = settings()
    return (
        cand.cosine >= s.cluster_cos_min
        and jaccard(title_tokens(cand.title), title_tokens(title)) >= s.cluster_title_min
        and jaccard(entity_tokens(cand.entities), entity_tokens(entities)) >= s.cluster_entity_min
    )


def pick_best(candidates: list[Candidate], title: str, entities: list[str]) -> Candidate | None:
    """Highest-cosine candidate that passes ALL three gates, or None."""
    passing = [c for c in candidates if same_event(c, title, entities)]
    return max(passing, key=lambda c: c.cosine) if passing else None


def display_score(authority: float, has_image: bool) -> float:
    """Source quality first, usable image second. (Wire-original detection
    is a later refinement -- the docs' 0.3 originality term awaits it.)"""
    return 0.5 * authority + 0.2 * (1.0 if has_image else 0.0)
