"""One-off: embed and entity-extract articles ingested before the column existed.

Reads bodies back from S3 (that is what storing raw text is FOR), batches
through the embedder, and never touches rows that already have a vector --
safe to interrupt and re-run.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from techtrend.platform import blobs, telemetry
from techtrend.platform.db import session_scope
from techtrend.shared.read.embed import embed_async, embedding_input
from techtrend.shared.read.entities import extract_entities

_PENDING = text("""
    SELECT id, title, text_key FROM articles
     WHERE embedding IS NULL
     ORDER BY id
     LIMIT :batch
""")

_SET = text("""
    UPDATE articles
       SET embedding = CAST(:embedding AS vector), entities = :entities
     WHERE id = :id
""")


async def backfill_embeddings(batch: int = 64) -> int:
    done = 0
    while True:
        async with session_scope() as s:
            rows = (await s.execute(_PENDING, {"batch": batch})).all()
        if not rows:
            return done

        bodies = await asyncio.gather(*(asyncio.to_thread(_body, r.text_key) for r in rows))
        vectors = await embed_async(
            [embedding_input(r.title, b) for r, b in zip(rows, bodies, strict=True)]
        )
        async with session_scope() as s:
            for r, b, v in zip(rows, bodies, vectors, strict=True):
                await s.execute(
                    _SET,
                    {"id": r.id, "embedding": str(v), "entities": extract_entities(r.title, b)},
                )
        done += len(rows)
        telemetry.log.info("backfill.progress", done=done)


def _body(text_key: str | None) -> str | None:
    if text_key is None:
        return None
    try:
        return blobs.get(text_key).decode("utf-8", errors="replace")
    except Exception:
        return None  # a missing blob degrades to title-only, same as paywalled
