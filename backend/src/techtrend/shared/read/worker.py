"""The read stage handler: one URL in, one `articles` row out.

Idempotent by UNIQUE (url_hash): re-delivery upserts the same row and never
touches `story_id` (Group owns that). A paywalled or bot-blocked page still
produces a metadata-only article from the feed's own hints -- invariant #4
costs coverage nothing.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from techtrend.platform import blobs, queue, telemetry
from techtrend.platform.db import session_scope
from techtrend.shared.collect.fetcher import RobotsDisallowed
from techtrend.shared.collect.worker import fetcher
from techtrend.shared.read.embed import embed_async, embedding_input
from techtrend.shared.read.entities import extract_entities
from techtrend.shared.read.extract import Extraction, extract, parse_date

_UPSERT = text("""
    INSERT INTO articles (url, url_hash, site_id, title, published_at, author,
                          image_url, language, description, text_key, html_key,
                          extraction, entities, embedding)
    VALUES (:url, :url_hash, :site_id, :title, :published_at, :author,
            :image_url, :language, :description, :text_key, :html_key,
            CAST(:extraction AS jsonb), :entities, CAST(:embedding AS vector))
    ON CONFLICT (url_hash) DO UPDATE
       SET title = EXCLUDED.title,
           author = EXCLUDED.author,
           description = COALESCE(EXCLUDED.description, articles.description),
           image_url = EXCLUDED.image_url,
           language = EXCLUDED.language,
           text_key = COALESCE(EXCLUDED.text_key, articles.text_key),
           html_key = COALESCE(EXCLUDED.html_key, articles.html_key),
           extraction = EXCLUDED.extraction,
           entities = EXCLUDED.entities,
           embedding = EXCLUDED.embedding
    RETURNING id
""")


async def run(job: queue.Job) -> None:
    url = job.payload["url"]
    site_id = job.payload["site_id"]

    blocked = False
    try:
        resp = await fetcher().get(url)
    except RobotsDisallowed:
        # We honour the disallow -- but the headline came legitimately from
        # the site's own feed, so a metadata-only article is still fair.
        blocked, resp = True, None
    except Exception as e:
        raise queue.RetryableError(repr(e)) from e  # network: back off and retry

    if resp is not None and resp.status in (404, 410):
        raise queue.FatalError(f"gone: {resp.status}")

    ext: Extraction | None = None
    html_key = text_key = None
    if blocked or resp is None:
        pass
    elif resp.status == 200:
        html = resp.body.decode("utf-8", errors="replace")
        ext = extract(html, url)
        hex_hash = blobs.hash_url(url)
        html_key = blobs.html_key(hex_hash)
        blobs.ensure_bucket()
        await asyncio.to_thread(blobs.put, html_key, resp.body, "text/html")
        if ext.body is not None:
            text_key = blobs.text_key(hex_hash)
            await asyncio.to_thread(blobs.put, text_key, ext.body.text)
    elif resp.status in (401, 403, 429):
        # Blocked or paywalled: the feed's own metadata still makes a valid,
        # first-class article (invariant #4 -- never bypass, never lose it).
        pass
    else:
        raise queue.RetryableError(f"status {resp.status}")

    meta = ext.meta if ext else None
    title = (meta.headline if meta else None) or job.payload.get("title_hint")
    if not title:
        raise queue.FatalError("no title from page or feed")

    published = (
        (meta.published_at if meta else None)
        or parse_date(job.payload.get("published_hint"))
        or datetime.now(UTC)
    )
    # Sites sometimes emit modified-time as datePublished; the future is a lie.
    now = datetime.now(UTC)
    if published > now + timedelta(hours=1):
        published = now

    body_text = ext.body.text if ext and ext.body else None
    (vector,) = await embed_async([embedding_input(title.strip(), body_text)])

    article_id = await _upsert(
        {
            "url": url,
            "url_hash": bytes.fromhex(blobs.hash_url(url)),
            "site_id": site_id,
            "title": title.strip(),
            "published_at": published,
            "author": meta.author if meta else None,
            "image_url": meta.image if meta else None,
            "language": (meta.language if meta else None) or "en",
            "description": meta.description if meta else None,
            "text_key": text_key,
            "html_key": html_key,
            "extraction": _extraction_json(ext, resp.status if resp else None),
            "entities": extract_entities(title, body_text),
            "embedding": str(vector),
        }
    )
    telemetry.log.info(
        "read.done",
        article_id=article_id,
        status=resp.status if resp else "robots",
        jsonld=bool(meta and meta.source == "jsonld"),
        body=text_key is not None,
    )


async def _upsert(params: dict[str, Any]) -> int:
    import json

    params = {**params, "extraction": json.dumps(params["extraction"])}
    async with session_scope() as s:
        article_id = (await s.execute(_UPSERT, params)).scalar_one()
        # Same transaction: the group job exists iff the article row does.
        await queue.enqueue(
            "group", f"group:article:{article_id}", {"article_id": article_id}, session=s
        )
        return int(article_id)


def _extraction_json(ext: Extraction | None, status: int | None) -> dict[str, Any]:
    if ext is None:
        return {"source": "hints", "status": status, "problems": ["blocked"]}
    return {
        "source": ext.meta.source if ext.meta.source != "none" else "fallback",
        "status": status,
        "confidence": ext.body.confidence if ext.body else None,
        "problems": ext.problems,
    }
