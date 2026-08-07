"""The judge stage handler: one AI call per story.

Guards, in order: `judged_at IS NULL` (idempotency), the AI call (fake or
real per TT_AI_FAKE), verify_numbers (invariant #7), verify_rewritten
(invariant #2), the authority guard on novelty, then importance -- computed
once, identical for every user (three-layers rule).

A refusal or a failed rewrite check marks the story UNJUDGED, never dropped:
the card shows headline + source without our summary, which is the honest
degrade (invariant #6 stays intact).
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

from techtrend.ai.client import client
from techtrend.platform import blobs, queue, telemetry
from techtrend.platform.config import settings
from techtrend.platform.db import session_scope
from techtrend.shared.judge.hedge import hedge_ratio
from techtrend.shared.judge.verify import verify_numbers, verify_rewritten

_LOAD_STORY = text("""
    SELECT id, subject_key, judged_at, created_at FROM stories WHERE id = :id
""")

_LOAD_ARTICLES = text("""
    SELECT a.title, a.text_key, a.published_at, s.name AS site_name, s.authority
      FROM articles a JOIN sites s ON s.id = a.site_id
     WHERE a.story_id = :story_id
     ORDER BY s.authority DESC
     LIMIT 50
""")

# Prior coverage on the subject: judged stories sharing the subject_key in
# the novelty window. Their stored facts are what "new" is measured against.
_PRIOR = text("""
    SELECT st.facts, st.created_at,
           (SELECT max(s2.authority) FROM articles a2 JOIN sites s2 ON s2.id = a2.site_id
             WHERE a2.story_id = st.id) AS max_authority
      FROM stories st
     WHERE st.subject_key = :subject_key
       AND st.id <> :story_id
       AND st.judged_at IS NOT NULL
       AND st.created_at > CAST(:created AS timestamptz) - make_interval(days => :days)
     ORDER BY st.created_at DESC
     LIMIT 20
""")

_SAVE = text("""
    UPDATE stories
       SET summary = :summary, story_type = :story_type,
           novelty_score = :novelty, hedge_score = :hedge,
           importance = :importance, facts = CAST(:facts AS jsonb),
           judged_at = now()
     WHERE id = :id AND judged_at IS NULL
""")

_MARK_UNJUDGED = text("""
    UPDATE stories SET judged_at = now(), hedge_score = :hedge, importance = :importance
     WHERE id = :id AND judged_at IS NULL
""")

TYPE_PENALTY = {
    "original_reporting": 0.0,
    "official_announcement": 0.1,
    "analysis": 0.2,
    "rewrite": 0.6,
    "roundup": 0.7,
    "routine_data": 0.8,
    "speculation": 0.9,
}


async def run(job: queue.Job) -> None:
    story_id = job.payload["story_id"]
    async with session_scope() as s:
        story = (await s.execute(_LOAD_STORY, {"id": story_id})).one_or_none()
    if story is None or story.judged_at is not None:
        return  # deleted or already judged: idempotent no-op

    async with session_scope() as s:
        articles = (await s.execute(_LOAD_ARTICLES, {"story_id": story_id})).all()
        prior = (
            await s.execute(
                _PRIOR,
                {
                    "subject_key": story.subject_key,
                    "story_id": story_id,
                    "created": story.created_at,
                    "days": settings().novelty_window_days,
                },
            )
        ).all()
        if story.subject_key is None:
            prior = []
    if not articles:
        raise queue.RetryableError("story has no articles yet")

    bodies = await asyncio.gather(*(asyncio.to_thread(_body, a.text_key) for a in articles))
    sources_text = _render_sources(articles, bodies)
    prior_facts = [f for p in prior for f in (p.facts or [])]
    max_authority = max(a.authority for a in articles)
    hedge = hedge_ratio(sources_text)

    try:
        result = await client().judge(
            title=articles[0].title, body=sources_text, prior_facts=prior_facts
        )
    except queue.RetryableError:
        raise
    except Exception as e:
        if type(e).__name__ == "Refused":
            await _unjudged(story_id, hedge, max_authority, len(articles), reason="refusal")
            return
        raise _classify(e) from e

    result = verify_numbers(result, sources_text)
    source_bodies = [b for b in bodies if b]
    if result.summary and not verify_rewritten(result.summary, source_bodies):
        # We would rather ship no summary than an infringing one (inv. #2).
        await _unjudged(story_id, hedge, max_authority, len(articles), reason="not_rewritten")
        return

    novelty = _authority_guard(result.novelty, max_authority, prior)
    importance = _importance(novelty, max_authority, len(articles), hedge, result.story_type)

    async with session_scope() as s:
        import json

        await s.execute(
            _SAVE,
            {
                "id": story_id,
                "summary": result.summary or None,
                "story_type": result.story_type,
                "novelty": novelty,
                "hedge": hedge,
                "importance": importance,
                "facts": json.dumps([f.model_dump() for f in result.facts]),
            },
        )
        await queue.enqueue("match", f"match:story:{story_id}", {"story_id": story_id}, session=s)
    telemetry.log.info("judge.done", story_id=story_id, novelty=novelty, type=result.story_type)


def _body(text_key: str | None, limit: int = 4000) -> str | None:
    if text_key is None:
        return None
    try:
        return blobs.get(text_key).decode("utf-8", errors="replace")[:limit]
    except Exception:
        return None


def _render_sources(articles: Sequence[Any], bodies: list[str | None]) -> str:
    parts = []
    for a, body in zip(articles, bodies, strict=True):
        parts.append(
            f'<article outlet="{a.site_name}" published="{a.published_at:%Y-%m-%d %H:%M}">\n'
            f"<headline>{a.title}</headline>\n{body or '(headline only)'}\n</article>"
        )
    return "\n".join(parts)


def _authority_guard(novelty: float, max_authority: float, prior: Sequence[Any]) -> float:
    """The same claim moving from a blog to Reuters IS new information.
    Without this, novelty systematically buries confirmations."""
    prior_max = max((p.max_authority or 0.0 for p in prior), default=0.0)
    jump = max_authority - prior_max
    return min(1.0, novelty + 0.4 * jump) if jump >= 0.3 and prior else novelty


def _importance(
    novelty: float, max_authority: float, n_articles: int, hedge: float, story_type: str
) -> float:
    return (
        0.45 * novelty
        + 0.25 * max_authority
        + 0.15 * min(1.0, math.log1p(n_articles) / math.log(50))
        - 0.10 * hedge
        - 0.05 * TYPE_PENALTY.get(story_type, 0.5)
    )


async def _unjudged(
    story_id: int, hedge: float, max_authority: float, n_articles: int, *, reason: str
) -> None:
    """An unjudged story is NOT a dropped story: null novelty ranks neutral,
    the card shows headline + source, attributed to the publisher."""
    importance = _importance(0.5, max_authority, n_articles, hedge, "original_reporting")
    async with session_scope() as s:
        await s.execute(_MARK_UNJUDGED, {"id": story_id, "hedge": hedge, "importance": importance})
        await queue.enqueue("match", f"match:story:{story_id}", {"story_id": story_id}, session=s)
    telemetry.log.info("judge.unjudged", story_id=story_id, reason=reason)


def _classify(e: Exception) -> Exception:
    """Map SDK errors onto queue semantics without importing anthropic here."""
    name = type(e).__name__
    if name in ("RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"):
        return queue.RetryableError(repr(e))
    status = getattr(e, "status_code", None)
    if isinstance(status, int) and status >= 500:
        return queue.RetryableError(repr(e))
    if isinstance(status, int):
        return queue.FatalError(repr(e))
    return queue.RetryableError(repr(e))
