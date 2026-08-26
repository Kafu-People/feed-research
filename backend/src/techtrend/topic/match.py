"""The precision half of matching: exact evaluation on a bounded candidate set.

`must` and `exclude` are HARD GATES, not weights. A user who says "not gaming
GPUs" means it, and no score overrides that. A gate expressed as a penalty is
a gate a high enough score defeats -- the same principle as the diversity
caps in personal/rank.py.

Terms match on WORD BOUNDARIES, not substrings: "AI" must not match "said".
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from techtrend.topic.fingerprint import normalise_term


@dataclass(frozen=True)
class StoryText:
    """What a story looks like to the matcher: title + publisher description
    + entities, normalised once. Bodies stay in S3 -- title and description
    carry the signal (Read guarantees they exist even for paywalled pages)."""

    text: str  # normalised, space-padded for boundary matching
    embedding: list[float] | None


def searchable(title: str, description: str | None, entities: list[str]) -> StoryText:
    parts = [title, description or "", " ".join(entities)]
    norm = normalise_term(" ".join(parts))
    return StoryText(text=f" {norm} ", embedding=None)


def _hit(term: str, text: str) -> bool:
    """Word-boundary containment on normalised text."""
    t = normalise_term(term)
    if not t:
        return False
    return f" {t} " in text or bool(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text))


def blocked(story: StoryText, terms: list[str] | tuple[str, ...]) -> str | None:
    """The first blocklist term this story hits, or None.

    Separate from a topic's own `exclude` on purpose. `exclude` is something a
    subscriber chose for one topic; this is a corpus-wide veto that a topic
    cannot opt out of and a new topic inherits automatically. Returning the
    term rather than a bool is what makes the skip loggable -- "blocked" with
    no reason is impossible to tune later.
    """
    for t in terms:
        if _hit(t, story.text):
            return normalise_term(t)
    return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def evaluate(
    *,
    must: list[str],
    should: list[str],
    exclude: list[str],
    entities: list[str],
    topic_embedding: list[float] | None,
    story: StoryText,
) -> tuple[float, list[str]]:
    """(score, matched_by). Gates are early returns, never penalty terms."""
    if any(_hit(e, story.text) for e in exclude):
        return 0.0, []
    hits = [t for t in must if _hit(t, story.text)]
    if not hits:
        return 0.0, []
    if entities and not any(_hit(e, story.text) for e in entities):
        return 0.0, []

    shoulds = [t for t in should if _hit(t, story.text)]
    hit_frac = min(1.0, len(hits) / 2)
    should_frac = min(1.0, len(shoulds) / 3)

    if topic_embedding is not None and story.embedding is not None:
        score = (
            0.5 * max(0.0, cosine(topic_embedding, story.embedding))
            + 0.3 * hit_frac
            + 0.2 * should_frac
        )
    else:
        # No vector available: redistribute onto the lexical signals.
        score = 0.6 * hit_frac + 0.4 * should_frac
    return score, hits + shoulds


def topic_embedding_input(title: str, must: list[str], should: list[str], ents: list[str]) -> str:
    """What a topic 'means' to the vector space: its own words."""
    return " ".join([title, *must, *should, *ents])
