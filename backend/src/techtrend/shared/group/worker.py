"""The group stage handler: attach an article to its story, or start one.

Idempotent: `story_id` is set once; a re-delivered job is a no-op. Candidates
are only articles already grouped, so two workers racing on the same event can
at worst create a duplicate story (a missed merge) -- the safe direction.
"""

from __future__ import annotations

from sqlalchemy import text

from techtrend.platform import queue, telemetry
from techtrend.platform.config import settings
from techtrend.platform.db import session_scope
from techtrend.shared.group.cluster import Candidate, pick_best

_LOAD = text("""
    SELECT a.id, a.title, a.entities, a.story_id, a.published_at, a.site_id,
           CAST(a.embedding AS text) AS embedding, s.tier
      FROM articles a JOIN sites s ON s.id = a.site_id
     WHERE a.id = :id
""")

# Recall: nearest grouped neighbours in the window. Precision happens in
# Python where all three signals are visible. Same-site articles never merge
# directly: one outlet's second article inside the window is almost always
# series coverage or a daily column -- a different event with similar words.
_CANDIDATES = text("""
    SELECT id, story_id, title, entities,
           1 - (embedding <=> CAST(:vec AS vector)) AS cosine
      FROM articles
     WHERE story_id IS NOT NULL
       AND id <> :id
       AND site_id <> :site_id
       AND embedding IS NOT NULL
       AND published_at BETWEEN CAST(:published AS timestamptz) - make_interval(hours => :window)
                            AND CAST(:published AS timestamptz) + make_interval(hours => :window)
     ORDER BY embedding <=> CAST(:vec AS vector)
     LIMIT 50
""")

_ATTACH = text("UPDATE articles SET story_id = :story_id WHERE id = :id AND story_id IS NULL")

_CREATE = text("""
    INSERT INTO stories (display_article_id, source_count, subject_key, embedding, created_at)
    VALUES (:article_id, 1, :subject_key, CAST(:embedding AS vector), now())
    RETURNING id
""")

# source_count is DISTINCT OUTLETS -- the "14 sources" on the card.
_REFRESH = text("""
    UPDATE stories st
       SET source_count = agg.n_sites,
           display_article_id = agg.display_id
      FROM (
        SELECT count(DISTINCT a.site_id) AS n_sites,
               (SELECT a2.id FROM articles a2 JOIN sites s2 ON s2.id = a2.site_id
                 WHERE a2.story_id = :story_id
                 ORDER BY 0.5 * s2.authority
                        + 0.2 * (CASE WHEN a2.image_url IS NOT NULL THEN 1 ELSE 0 END) DESC,
                          a2.published_at ASC
                 LIMIT 1) AS display_id
          FROM articles a WHERE a.story_id = :story_id
      ) agg
     WHERE st.id = :story_id
""")


async def run(job: queue.Job) -> None:
    async with session_scope() as s:
        art = (await s.execute(_LOAD, {"id": job.payload["article_id"]})).one_or_none()
    if art is None or art.story_id is not None:
        return  # deleted, or already grouped: idempotent no-op
    if art.embedding is None:
        raise queue.RetryableError("article has no embedding yet")

    async with session_scope() as s:
        rows = (
            await s.execute(
                _CANDIDATES,
                {
                    "id": art.id,
                    "site_id": art.site_id,
                    "vec": art.embedding,
                    "published": art.published_at,
                    "window": settings().group_window_hours,
                },
            )
        ).all()

    best = pick_best(
        [
            Candidate(
                article_id=r.id,
                story_id=r.story_id,
                cosine=float(r.cosine),
                title=r.title,
                entities=list(r.entities or []),
            )
            for r in rows
        ],
        art.title,
        list(art.entities or []),
    )

    async with session_scope() as s:
        if best is not None:
            story_id = best.story_id
            await s.execute(_ATTACH, {"story_id": story_id, "id": art.id})
            await s.execute(_REFRESH, {"story_id": story_id})
        else:
            story_id = (
                await s.execute(
                    _CREATE,
                    {
                        "article_id": art.id,
                        "subject_key": _subject_key(list(art.entities or [])),
                        "embedding": art.embedding,
                    },
                )
            ).scalar_one()
            await s.execute(_ATTACH, {"story_id": story_id, "id": art.id})
        # Same transaction: the judge job exists iff the grouping committed.
        await queue.enqueue(
            "judge",
            f"judge:story:{story_id}",
            {"story_id": story_id},
            priority=10 if art.tier == "A" else 100,
            session=s,
        )
    telemetry.log.info("group.done", article_id=art.id, story_id=story_id, merged=best is not None)


def _subject_key(entities: list[str]) -> str | None:
    """A coarse handle for 'coverage of the same subject' -- the novelty
    window ([Judge]) retrieves prior stories by it. Top entities, sorted so
    ordering differences don't split a subject."""
    if not entities:
        return None
    return "|".join(sorted(e.lower() for e in entities[:3]))
