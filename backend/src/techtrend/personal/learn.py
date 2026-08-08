"""Feedback -> weights. The whole personal model, learned from clean signals.

Everything here writes ONLY the personal layer (invariant #11): weights and
suggestions. Learned excludes are PROPOSED as suggestions, never applied to
the shared topic row (invariant #12).

Position bias: a skip at position 1 is a real signal; a skip at position 10
mostly means the user never got there. Positives invert -- a tap at position
10 overcame its position and counts a little extra.
"""

from __future__ import annotations

import math
import time
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import text

from techtrend.platform import queue, telemetry
from techtrend.platform.db import session_scope

LEARNING_RATE = 0.05
WEIGHT_CLAMP = 0.5
# Signals we learn from, with their base strength. Absences are deliberate:
# there is no CLICK anywhere in the schema (invariant #8), and SHOWN alone
# teaches nothing.
SIGNAL: dict[str, float] = {
    "tapped_through": 1.0,
    "dwell": 0.6,
    "saved": 1.2,
    "shared": 1.2,
    "best_of_day": 1.5,
    "expanded": 0.4,
    "scrolled_past": -0.15,
    "skipped": -0.3,
    "hidden": -1.0,
}
# Hides sharing a keyword this many times become a proposed personal exclude.
HIDE_SUGGESTION_THRESHOLD = 3


def propensity(position: int | None) -> float:
    """How likely a card at this position was even seen. Position 0 ~ 1.0,
    decaying with depth."""
    if position is None:
        return 0.7
    return 1.0 / math.log2(position + 2)


def signal_value(kind: str, position: int | None, dwell_ms: int | None) -> float:
    base = SIGNAL.get(kind, 0.0)
    if base == 0.0:
        return 0.0
    if kind == "dwell":
        # Sub-5s dwell is a bounce -- weak negative, not positive.
        if dwell_ms is not None and dwell_ms < 5000:
            base = -0.2
    p = propensity(position)
    if base > 0:
        # The deep card overcame its position: correct UP (bounded).
        return base * min(2.0, 1.0 / p)
    # The deep card was probably never seen: discount the negative.
    return base * p


_UNPROCESSED = text("""
    SELECT e.id, e.kind, e.position, e.dwell_ms, e.story_id,
           st.story_type, si.name AS source_name
      FROM events e
      LEFT JOIN stories st ON st.id = e.story_id
      LEFT JOIN articles a ON a.id = st.display_article_id
      LEFT JOIN sites si ON si.id = a.site_id
     WHERE e.user_id = :uid AND e.processed_at IS NULL
     ORDER BY e.id
     LIMIT 2000
""")

# Which keywords produced the match, restricted to this user's subscriptions.
_MATCHED_BY = text("""
    SELECT m.story_id, m.topic_id, m.matched_by
      FROM matches m
      JOIN subscriptions s ON s.topic_id = m.topic_id
     WHERE s.user_id = :uid AND m.story_id = ANY(:story_ids)
""")

_UPSERT_WEIGHT = text("""
    INSERT INTO weights (user_id, kind, key, value, updated_at)
    VALUES (:uid, :kind, :key, :value, now())
    ON CONFLICT (user_id, kind, key) DO UPDATE
       SET value = GREATEST(:lo, LEAST(:hi, weights.value + :value)),
           updated_at = now()
""")

_MARK = text("UPDATE events SET processed_at = now() WHERE id = ANY(:ids)")

_SUGGEST = text("""
    INSERT INTO suggestions (user_id, topic_id, kind, payload, evidence, state)
    SELECT :uid, :topic_id, 'personal_exclude', CAST(:payload AS jsonb), :evidence, 'pending'
     WHERE NOT EXISTS (
        SELECT 1 FROM suggestions
         WHERE user_id = :uid AND topic_id = :topic_id
           AND kind = 'personal_exclude' AND payload = CAST(:payload AS jsonb)
           AND state = 'pending'
     )
""")


async def run(job: queue.Job) -> None:
    """Coalesced per user: fold every unprocessed event into the weights."""
    uid = job.payload["user_id"]
    async with session_scope() as s:
        events = (await s.execute(_UNPROCESSED, {"uid": uid})).all()
        if not events:
            return
        story_ids = sorted({e.story_id for e in events if e.story_id is not None})
        matched = (
            (await s.execute(_MATCHED_BY, {"uid": uid, "story_ids": story_ids})).all()
            if story_ids
            else []
        )

    keywords_by_story: dict[int, list[tuple[int, list[str]]]] = {}
    for m in matched:
        keywords_by_story.setdefault(m.story_id, []).append((m.topic_id, list(m.matched_by or [])))

    deltas: defaultdict[tuple[str, str], float] = defaultdict(float)
    hide_terms: Counter[tuple[int, str]] = Counter()
    for e in events:
        v = signal_value(e.kind, e.position, e.dwell_ms)
        if v == 0.0:
            continue
        if e.story_type:
            deltas[("type", e.story_type)] += v
        if e.source_name:
            deltas[("source", e.source_name)] += v
        for topic_id, kws in keywords_by_story.get(e.story_id or -1, []):
            for kw in kws:
                deltas[("keyword", kw)] += v
                if e.kind == "hidden":
                    hide_terms[(topic_id, kw)] += 1

    async with session_scope() as s:
        for (kind, key), delta in deltas.items():
            await s.execute(
                _UPSERT_WEIGHT,
                {
                    "uid": uid,
                    "kind": kind,
                    "key": key,
                    "value": max(-WEIGHT_CLAMP, min(WEIGHT_CLAMP, delta * LEARNING_RATE)),
                    "lo": -WEIGHT_CLAMP,
                    "hi": WEIGHT_CLAMP,
                },
            )
        # Learned excludes are PROPOSED (invariant #12): the shared topic row
        # is never touched, and nothing changes without the user accepting.
        import json

        for (topic_id, term), n in hide_terms.items():
            if n >= HIDE_SUGGESTION_THRESHOLD:
                await s.execute(
                    _SUGGEST,
                    {
                        "uid": uid,
                        "topic_id": topic_id,
                        "payload": json.dumps({"term": term}),
                        "evidence": f"hidden {n} stories matching '{term}'",
                    },
                )
        await s.execute(_MARK, {"ids": [e.id for e in events]})
    telemetry.log.info("learn.done", user_id=uid, events=len(events), weights=len(deltas))


def enqueue_for(user_id: int, session: Any = None) -> Any:
    """Coalesced per 5-minute bucket: bursts of events fold into one job,
    and the next burst gets a fresh key once the bucket rolls over."""
    bucket = int(time.time() // 300)
    return queue.enqueue(
        "feedback",
        f"feedback:user:{user_id}:{bucket}",
        {"user_id": user_id},
        delay_s=60.0,
        session=session,
    )
