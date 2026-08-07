"""End-to-end through the real API against real Postgres."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from techtrend.api.app import create_app
from techtrend.platform.db import session_scope


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def _auth(api: AsyncClient, email: str = "a@example.com") -> dict[str, str]:
    r = await api.post("/v1/auth/signup", json={"email": email, "password": "hunter2hunter2"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_story(*, title: str, importance: float, source: str, hours_ago: int = 1) -> int:
    """Insert a site + story + display article, and return the story id."""
    async with session_scope() as s:
        site_id = await s.scalar(
            text(
                "INSERT INTO sites (domain, name, tier, authority) "
                "VALUES (:d, :n, 'A', 0.9) ON CONFLICT (domain) DO UPDATE SET name=EXCLUDED.name "
                "RETURNING id"
            ),
            {"d": f"{source.lower()}.com", "n": source},
        )
        story_id = await s.scalar(
            text(
                "INSERT INTO stories (source_count, summary, story_type, novelty_score,"
                " hedge_score, importance, judged_at) "
                "VALUES (14, :sm, 'original_reporting', 0.8, 0.1, :imp, now()) RETURNING id"
            ),
            {"sm": f"{title}. Reported across outlets.", "imp": importance},
        )
        url = f"https://{source.lower()}.com/{story_id}"
        article_id = await s.scalar(
            text(
                "INSERT INTO articles (url, url_hash, site_id, title, published_at, story_id)"
                " VALUES (:u, :h, :sid, :t, :p, :st) RETURNING id"
            ),
            {
                "u": url,
                "h": hashlib.sha256(url.encode()).digest(),
                "sid": site_id,
                "t": title,
                "p": datetime.now(UTC) - timedelta(hours=hours_ago),
                "st": story_id,
            },
        )
        await s.execute(
            text("UPDATE stories SET display_article_id=:a WHERE id=:s"),
            {"a": article_id, "s": story_id},
        )
    return int(story_id)


async def _match(story_id: int, topic_id: int, score: float = 0.9) -> None:
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO matches (topic_id, story_id, match_score, matched_by)"
                " VALUES (:t, :s, :sc, ARRAY['h100'])"
            ),
            {"t": topic_id, "s": story_id, "sc": score},
        )


# ------------------------------------------------------------------ ops


async def test_healthz_and_readyz(api: AsyncClient) -> None:
    assert (await api.get("/healthz")).json()["status"] == "ok"
    assert (await api.get("/readyz")).json()["status"] == "ready"


# ----------------------------------------------------------------- auth


async def test_signup_login_and_guarded_route(api: AsyncClient) -> None:
    headers = await _auth(api)
    assert (await api.get("/v1/dashboard")).status_code == 401
    assert (await api.get("/v1/dashboard", headers=headers)).status_code == 200

    r = await api.post(
        "/v1/auth/login", json={"email": "a@example.com", "password": "hunter2hunter2"}
    )
    assert r.status_code == 200
    r = await api.post(
        "/v1/auth/login", json={"email": "a@example.com", "password": "wrongwrongwrong"}
    )
    assert r.status_code == 401


# --------------------------------------------------------------- topics


async def test_draft_then_save_a_topic(api: AsyncClient) -> None:
    headers = await _auth(api)

    r = await api.post(
        "/v1/topics/draft",
        json={"sentence": "AI chips and export restrictions, especially Nvidia and China"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["must"], "the distiller must produce keywords"
    assert "per_day" in draft  # the rate is shown BEFORE the topic is wrong

    r = await api.post(
        "/v1/topics", json={**draft, "title": "AI chip export controls"}, headers=headers
    )
    assert r.status_code == 201, r.text
    assert r.json()["subscriber_count"] == 1

    assert len((await api.get("/v1/topics", headers=headers)).json()) == 1


async def test_identical_topics_collapse_to_one_row() -> None:
    """Ten thousand people typing a version of "AI news" collapse to a handful
    of rows: one matching job, many readers."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as api:
        h1 = await _auth(api, "one@example.com")
        h2 = await _auth(api, "two@example.com")

        body = {
            "title": "AI chips",
            "must": ["AI chip", "GPU"],
            "should": [],
            "entities": ["Nvidia"],
            "exclude": [],
        }
        # Same interest, different spelling/order/case.
        body2 = {
            "title": "AI chips (mine)",
            "must": ["gpu", "ai-chip"],
            "should": [],
            "entities": ["nvidia"],
            "exclude": [],
        }

        a = await api.post("/v1/topics", json=body, headers=h1)
        b = await api.post("/v1/topics", json=body2, headers=h2)

        assert a.json()["id"] == b.json()["id"], "fingerprints must collide"
        assert b.json()["subscriber_count"] == 2

        async with session_scope() as s:
            n = await s.scalar(text("SELECT count(*) FROM topics"))
        assert n == 1


# ------------------------------------------------------------ dashboard


async def test_dashboard_ranks_dedupes_caps_and_does_not_pad(api: AsyncClient) -> None:
    headers = await _auth(api)
    topic = (
        await api.post(
            "/v1/topics",
            json={
                "title": "AI chips",
                "must": ["chip"],
                "should": [],
                "entities": [],
                "exclude": [],
            },
            headers=headers,
        )
    ).json()

    for i, imp in enumerate([0.9, 0.5, 0.7]):
        sid = await _seed_story(title=f"Story {i}", importance=imp, source=f"Src{i}")
        await _match(sid, topic["id"])

    r = await api.get("/v1/dashboard", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    # Ranked by importance x match x freshness x personal.
    assert [c["headline"] for c in body["cards"]] == ["Story 0", "Story 2", "Story 1"]
    # Three good things -> three cards. No filler. (invariant #10)
    assert len(body["cards"]) == 3
    assert body["done"] is True
    # Invariant #1: no route by which a body could be served.
    assert "text" not in body["cards"][0]
    assert body["cards"][0]["source_count"] == 14


async def test_a_story_matching_two_topics_appears_once(api: AsyncClient) -> None:
    headers = await _auth(api)
    t1 = (
        await api.post(
            "/v1/topics",
            json={
                "title": "AI chips",
                "must": ["chip"],
                "should": [],
                "entities": [],
                "exclude": [],
            },
            headers=headers,
        )
    ).json()
    t2 = (
        await api.post(
            "/v1/topics",
            json={
                "title": "Export controls",
                "must": ["export"],
                "should": [],
                "entities": [],
                "exclude": [],
            },
            headers=headers,
        )
    ).json()

    sid = await _seed_story(title="Commerce adds four fabs", importance=0.9, source="Reuters")
    await _match(sid, t1["id"], 0.8)
    await _match(sid, t2["id"], 0.95)

    cards = (await api.get("/v1/dashboard", headers=headers)).json()["cards"]
    assert len(cards) == 1, "invariant #6: one story appears once"
    assert len(cards[0]["topic_labels"]) == 2, "labelled with BOTH topics"


async def test_opted_out_publisher_disappears_from_serving(api: AsyncClient) -> None:
    """Invariant #3 gates serving, not just collection."""
    headers = await _auth(api)
    topic = (
        await api.post(
            "/v1/topics",
            json={"title": "t", "must": ["chip"], "should": [], "entities": [], "exclude": []},
            headers=headers,
        )
    ).json()
    sid = await _seed_story(title="Something", importance=0.9, source="Grumpy")
    await _match(sid, topic["id"])

    assert len((await api.get("/v1/dashboard", headers=headers)).json()["cards"]) == 1

    async with session_scope() as s:
        await s.execute(text("UPDATE sites SET opt_out_at = now() WHERE name='Grumpy'"))
        await s.execute(text("DELETE FROM seen"))  # so it would otherwise re-appear

    assert (await api.get("/v1/dashboard", headers=headers)).json()["cards"] == []


async def test_quiet_day_is_allowed_to_be_quiet(api: AsyncClient) -> None:
    headers = await _auth(api)
    body = (await api.get("/v1/dashboard", headers=headers)).json()
    assert body["cards"] == []
    assert body["done"] is True  # "That's today." -- not an error state


# ------------------------------------------------------------- feedback


async def test_events_are_accepted_and_recorded(api: AsyncClient) -> None:
    headers = await _auth(api)
    sid = await _seed_story(title="X", importance=0.5, source="Reuters")

    r = await api.post(
        "/v1/events",
        json=[
            {"story_id": sid, "kind": "tapped_through", "position": 0},
            {"story_id": sid, "kind": "skipped", "position": 3},
            {"story_id": sid, "kind": "hidden", "reason": "already knew it", "position": 3},
        ],
        headers=headers,
    )
    assert r.status_code == 202
    assert r.json()["accepted"] == 3

    async with session_scope() as s:
        kinds = list(await s.scalars(text("SELECT kind FROM events ORDER BY id")))
        reason = await s.scalar(text("SELECT reason FROM events WHERE kind='hidden'"))
    assert kinds == ["tapped_through", "skipped", "hidden"]
    assert reason == "already knew it"


async def test_click_is_not_an_acceptable_event_kind(api: AsyncClient) -> None:
    """Invariant #8, enforced at the schema boundary."""
    headers = await _auth(api)
    r = await api.post("/v1/events", json=[{"story_id": 1, "kind": "click"}], headers=headers)
    assert r.status_code == 422
