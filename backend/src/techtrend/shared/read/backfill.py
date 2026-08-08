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


_DESC_PENDING = text("""
    SELECT id, html_key FROM articles
     WHERE description IS NULL AND html_key IS NOT NULL
     ORDER BY id
     LIMIT :batch
""")

_DESC_SET = text("UPDATE articles SET description = :d WHERE id = :id")
_DESC_SKIP = text("UPDATE articles SET description = '' WHERE id = :id")


async def backfill_descriptions(batch: int = 200) -> int:
    """Re-extract publisher descriptions from stored raw HTML.

    This re-run is what keeping raw HTML in S3 is FOR -- no re-crawl.
    Articles whose HTML has no description get '' so the query converges.
    """
    from techtrend.shared.read.extract import extract_description

    done = 0
    while True:
        async with session_scope() as s:
            rows = (await s.execute(_DESC_PENDING, {"batch": batch})).all()
        if not rows:
            return done
        htmls = await asyncio.gather(*(asyncio.to_thread(_body, r.html_key) for r in rows))
        async with session_scope() as s:
            for r, html in zip(rows, htmls, strict=True):
                desc = extract_description(html) if html else None
                if desc:
                    await s.execute(_DESC_SET, {"id": r.id, "d": desc})
                else:
                    await s.execute(_DESC_SKIP, {"id": r.id})
        done += len(rows)
        telemetry.log.info("backfill.descriptions", done=done)
