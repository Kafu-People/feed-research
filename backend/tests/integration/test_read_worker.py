"""Read against real Postgres + MinIO: page -> blobs -> articles row -> group job."""

from __future__ import annotations

import pytest
import respx
from sqlalchemy import text

from techtrend.platform import blobs, queue
from techtrend.platform.db import session_scope
from techtrend.shared.collect import worker as collect_worker
from techtrend.shared.read import worker

pytestmark = pytest.mark.integration

WORDS = " ".join(f"substantive sentence number {i} about chips" for i in range(40))
PAGE = f"""<html><head>
<script type="application/ld+json">
{{"@type":"NewsArticle","headline":"H100 supply loosens",
  "datePublished":"2026-08-07T06:00:00Z","author":"R. Porter",
  "image":"https://ex.com/pic.jpg","inLanguage":"en"}}
</script></head><body><article><p>{WORDS}</p></article></body></html>"""


@pytest.fixture(autouse=True)
def fresh_fetcher() -> None:
    collect_worker._fetcher = None


async def _site() -> int:
    async with session_scope() as s:
        return (
            await s.execute(
                text(
                    "INSERT INTO sites (domain, name, tier) VALUES ('ex.com','Ex','A') RETURNING id"
                )
            )
        ).scalar_one()


def _job(url: str, site_id: int, **hints: str | None) -> queue.Job:
    return queue.Job(
        id=1,
        stage="read",
        key="read:article:x",
        payload={"url": url, "site_id": site_id, **hints},
        attempts=1,
        max_attempts=5,
    )


@respx.mock
async def test_page_becomes_article_with_blobs_and_group_job() -> None:
    site_id = await _site()
    respx.get("https://ex.com/robots.txt").respond(404)
    respx.get("https://ex.com/one").respond(200, content=PAGE.encode())

    await worker.run(_job("https://ex.com/one", site_id))

    async with session_scope() as s:
        art = (await s.execute(text("SELECT * FROM articles"))).one()
    assert art.title == "H100 supply loosens"
    assert art.author == "R. Porter"
    assert art.extraction["source"] == "jsonld"
    assert b"substantive sentence" in blobs.get(art.text_key)
    assert b"NewsArticle" in blobs.get(art.html_key)

    (group_job,) = await queue.claim(["group"])
    assert group_job.payload == {"article_id": art.id}


@respx.mock
async def test_rerun_is_idempotent_one_row_one_group_job() -> None:
    site_id = await _site()
    respx.get("https://ex.com/robots.txt").respond(404)
    respx.get("https://ex.com/one").respond(200, content=PAGE.encode())

    await worker.run(_job("https://ex.com/one", site_id))
    await worker.run(_job("https://ex.com/one", site_id))

    async with session_scope() as s:
        n_articles = (await s.execute(text("SELECT count(*) FROM articles"))).scalar_one()
        n_group = (
            await s.execute(text("SELECT count(*) FROM jobs WHERE stage='group'"))
        ).scalar_one()
    assert (n_articles, n_group) == (1, 1)


@respx.mock
async def test_paywalled_403_still_yields_metadata_only_article() -> None:
    """Invariant #4: blocked pages are first-class articles via feed hints."""
    site_id = await _site()
    respx.get("https://ex.com/robots.txt").respond(404)
    respx.get("https://ex.com/pay").respond(403)

    await worker.run(
        _job(
            "https://ex.com/pay",
            site_id,
            title_hint="Behind the wall",
            published_hint="2026-08-07T05:00:00+00:00",
        )
    )
    async with session_scope() as s:
        art = (await s.execute(text("SELECT * FROM articles"))).one()
    assert art.title == "Behind the wall"
    assert art.text_key is None and art.html_key is None
    assert art.extraction["source"] == "hints"


@respx.mock
async def test_robots_disallowed_page_still_yields_metadata_article() -> None:
    """WSJ disallows /articles/ -- we honour it AND keep the feed's headline."""
    site_id = await _site()
    respx.get("https://ex.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /articles/")
    await worker.run(_job("https://ex.com/articles/x", site_id, title_hint="Robots-walled story"))
    async with session_scope() as s:
        art = (await s.execute(text("SELECT * FROM articles"))).one()
    assert art.title == "Robots-walled story"
    assert art.html_key is None  # the page was truly never fetched
    assert art.extraction["source"] == "hints"


@respx.mock
async def test_404_is_fatal_not_retried() -> None:
    site_id = await _site()
    respx.get("https://ex.com/robots.txt").respond(404)
    respx.get("https://ex.com/gone").respond(404)
    with pytest.raises(queue.FatalError):
        await worker.run(_job("https://ex.com/gone", site_id))


@respx.mock
async def test_page_without_title_anywhere_is_fatal() -> None:
    site_id = await _site()
    respx.get("https://ex.com/robots.txt").respond(404)
    respx.get("https://ex.com/blank").respond(200, content=b"<html><body>x</body></html>")
    with pytest.raises(queue.FatalError):
        await worker.run(_job("https://ex.com/blank", site_id))
