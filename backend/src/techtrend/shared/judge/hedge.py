"""Hedge density -- speculation detection without a model call.

'Reportedly', 'sources say', 'rumored' are honest words for uncertain
reporting; a story built mostly of them should rank below confirmed fact.
A lexicon ratio is crude and cheap, and one fewer AI call per story.
"""

from __future__ import annotations

import re

_HEDGES = (
    "reportedly",
    "allegedly",
    "rumored",
    "rumoured",
    "rumors",
    "rumours",
    "may",
    "might",
    "could",
    "possibly",
    "perhaps",
    "likely",
    "unlikely",
    "appears",
    "seems",
    "suggests",
    "unconfirmed",
    "speculation",
    "expected",
    "sources say",
    "sources said",
    "according to sources",
    "people familiar",
    "is said to",
    "are said to",
    "claims",
    "claimed",
    "supposedly",
)
_PATTERN = re.compile(r"\b(?:" + "|".join(re.escape(h) for h in _HEDGES) + r")\b", re.I)
_WORD = re.compile(r"[\w']+")


def hedge_ratio(text: str) -> float:
    """Hedge hits per 100 words, capped into [0, 1]."""
    words = len(_WORD.findall(text))
    if words == 0:
        return 0.0
    hits = len(_PATTERN.findall(text))
    return min(1.0, hits * 100 / words / 10)  # 10 hedges per 100 words -> 1.0
