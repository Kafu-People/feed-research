"""The match stage: one story in, rows in `matches` out.

Two-phase, as designed: RECALL is cheap and allowed to over-return (the
reverse index by term, plus nearest topics by vector); PRECISION is
`evaluate()` -- the same function the draft preview uses, so the preview
can never lie about what the pipeline would do.

Idempotent: PRIMARY KEY (topic_id, story_id) upsert.
"""

from __future__ import annotations

import re

from sqlalchemy import text

from techtrend.platform import queue, telemetry
from techtrend.platform.config import settings
from techtrend.platform.db import session_scope
from techtrend.topic.match import StoryText, evaluate, searchable

_LOAD_STORY = text("""
    SELECT st.id, a.title, a.description, a.entities,
           CAST(st.embedding AS text) AS embedding
      FROM stories st JOIN articles a ON a.id = st.display_article_id
     WHERE st.id = :id
""")

# Recall phase 1: the reverse index. Story tokens looked up IN it.
_BY_TERM = text("SELECT DISTINCT topic_id FROM topic_terms WHERE term = ANY(:tokens)")

# Recall phase 2: nearest topics by meaning -- catches paraphrases keywords miss.
_BY_VECTOR = text("""
    SELECT id FROM topics
     WHERE embedding IS NOT NULL
     ORDER BY embedding <=> CAST(:vec AS vector)
     LIMIT :topk
""")

_LOAD_TOPICS = text("""
    SELECT id, must, should, exclude, entities, floor,
           CAST(embedding AS text) AS embedding
      FROM topics WHERE id = ANY(:ids)
""")

_UPSERT = text("""
    INSERT INTO matches (topic_id, story_id, match_score, matched_by, matched_at)
    VALUES (:topic_id, :story_id, :score, :matched_by, now())
    ON CONFLICT (topic_id, story_id) DO UPDATE
       SET match_score = EXCLUDED.match_score,
           matched_by = EXCLUDED.matched_by,
           matched_at = EXCLUDED.matched_at
""")

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text_: str) -> list[str]:
    """Uni/bi/tri-grams -- topic_terms holds normalised multiword terms."""
    words = _WORD.findall(text_.lower())
    grams = set(words)
    grams.update(" ".join(words[i : i + 2]) for i in range(len(words) - 1))
    grams.update(" ".join(words[i : i + 3]) for i in range(len(words) - 2))
    return list(grams)


def _parse_vec(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    return [float(x) for x in raw.strip("[]").split(",")]


async def run(job: queue.Job) -> None:
    story_id = job.payload["story_id"]
    async with session_scope() as s:
        row = (await s.execute(_LOAD_STORY, {"id": story_id})).one_or_none()
    if row is None:
        return  # story deleted: idempotent no-op

    st = searchable(row.title, row.description, list(row.entities or []))
    story = StoryText(text=st.text, embedding=_parse_vec(row.embedding))

    async with session_scope() as s:
        by_term = {
            r[0] for r in (await s.execute(_BY_TERM, {"tokens": _tokens(st.text)})).all()
        }
        by_vector: set[int] = set()
        if story.embedding is not None:
            by_vector = {
                r[0]
                for r in (
                    await s.execute(
                        _BY_VECTOR,
                        {"vec": row.embedding, "topk": settings().match_vector_topk},
                    )
                ).all()
            }
        candidate_ids = list(by_term | by_vector)
        if not candidate_ids:
            return
        topics = (await s.execute(_LOAD_TOPICS, {"ids": candidate_ids})).all()

    rows = []
    for t in topics:
        score, matched_by = evaluate(
            must=list(t.must or []),
            should=list(t.should or []),
            exclude=list(t.exclude or []),
            entities=list(t.entities or []),
            topic_embedding=_parse_vec(t.embedding),
            story=story,
        )
        if score >= t.floor:
            rows.append({"topic_id": t.id, "story_id": story_id,
                         "score": score, "matched_by": matched_by})

    if rows:
        async with session_scope() as s:
            for r in rows:
                await s.execute(_UPSERT, r)
    telemetry.log.info(
        "match.done", story_id=story_id, candidates=len(candidate_ids), matched=len(rows)
    )
