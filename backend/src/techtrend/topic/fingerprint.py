"""Normalise -> hash -> collide.

Identical topics become ONE row with many subscribers. This is the second of the
two decisions that make the economics work, and the biggest unvalidated
assumption in the system: measure the distinct-topic ratio on real signups.
"""

from __future__ import annotations

import hashlib
import re

_SEPARATORS = re.compile(r"[-_/.]+")
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def normalise_term(term: str) -> str:
    """Lowercase, treat separators as spaces, drop other punctuation.

    Hyphens MUST become spaces: "AI chip", "AI-chip" and "ai_chip" are the same
    interest, and if they fingerprint differently the distinct-topic count rises
    and matching stops being flat in users -- the one measurement the whole cost
    model rests on.
    """
    t = _SEPARATORS.sub(" ", term.lower().strip())
    t = _PUNCT.sub("", t)
    return _WS.sub(" ", t).strip()


def normalise(terms: list[str]) -> list[str]:
    """Lowercase, strip punctuation, dedupe, sort. Order must not matter."""
    return sorted({normalise_term(t) for t in terms if normalise_term(t)})


def fingerprint(
    must: list[str], should: list[str], entities: list[str], exclude: list[str]
) -> bytes:
    parts = [
        ",".join(normalise(must)),
        ",".join(normalise(should)),
        ",".join(normalise(entities)),
        ",".join(normalise(exclude)),
    ]
    return hashlib.sha256("|".join(parts).encode()).digest()
