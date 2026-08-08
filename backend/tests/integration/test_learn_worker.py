"""M6 against real Postgres: events -> weights, suggestions proposed not applied."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from techtrend.personal import learn
from techtrend.platform import queue
from techtrend.platform.db import session_scope

pytestmark = pytest.mark.integration


async def _fixture() -> tuple[int, int, int]:
    """User subscribed to a topic with one matched story."""
    async with session_scope() as s:
        uid = (
            await s.execute(
                text("INSERT INTO users (email, password_hash) VALUES ('u@x.com','h') RETURNING id")
            )
        ).scalar_one()
        site = (
            await s.execute(
                text(
                    "INSERT INTO sites (domain,name,authority)"
                    " VALUES ('ex.com','Ex',0.8) RETURNING id"
                )
            )
        ).scalar_one()
        story = (
            await s.execute(
                text("INSERT INTO stories (story_type) VALUES ('speculation') RETURNING id")
            )
        ).scalar_one()
        art = (
            await s.execute(
                text("""INSERT INTO articles (url,url_hash,site_id,title,published_at,story_id)
                        VALUES ('https://ex.com/1','\\x01',:sid,'GPU rumor roundup',now(),:st)
                        RETURNING id"""),
                {"sid": site, "st": story},
            )
        ).scalar_one()
        await s.execute(
            text("UPDATE stories SET display_article_id=:a WHERE id=:st"), {"a": art, "st": story}
        )
        topic = (
            await s.execute(
                text(
                    "INSERT INTO topics (fingerprint,title,must)"
                    " VALUES ('\\x02','Chips','{gpu}') RETURNING id"
                )
            )
        ).scalar_one()
        await s.execute(
            text("INSERT INTO subscriptions (user_id,topic_id) VALUES (:u,:t)"),
            {"u": uid, "t": topic},
        )
        await s.execute(
            text("""INSERT INTO matches (topic_id,story_id,match_score,matched_by)
                    VALUES (:t,:st,0.8,'{gpu}')"""),
            {"t": topic, "st": story},
        )
    return uid, story, topic


def _job(uid: int) -> queue.Job:
    return queue.Job(
        id=1,
        stage="feedback",
        key=f"feedback:user:{uid}",
        payload={"user_id": uid},
        attempts=1,
        max_attempts=5,
    )


async def test_hides_move_weights_down_and_propose_never_apply() -> None:
    uid, story, topic = await _fixture()
    async with session_scope() as s:
        for _ in range(3):
            await s.execute(
                text("""INSERT INTO events (user_id,story_id,kind,position)
                        VALUES (:u,:st,'hidden',0)"""),
                {"u": uid, "st": story},
            )
    await learn.run(_job(uid))

    async with session_scope() as s:
        w = (
            await s.execute(
                text("SELECT value FROM weights WHERE user_id=:u AND kind='keyword' AND key='gpu'"),
                {"u": uid},
            )
        ).scalar_one()
        n_sugg = (
            await s.execute(
                text("""SELECT count(*) FROM suggestions
                        WHERE user_id=:u AND topic_id=:t AND kind='personal_exclude'
                          AND state='pending' AND payload->>'term'='gpu'"""),
                {"u": uid, "t": topic},
            )
        ).scalar_one()
        # Invariants #11/#12: shared topic untouched, subscription untouched
        # until the user accepts.
        topic_exclude = (
            await s.execute(text("SELECT exclude FROM topics WHERE id=:t"), {"t": topic})
        ).scalar_one()
        personal = (
            await s.execute(
                text("SELECT personal_excludes FROM subscriptions WHERE user_id=:u"), {"u": uid}
            )
        ).scalar_one()
        unprocessed = (
            await s.execute(
                text("SELECT count(*) FROM events WHERE user_id=:u AND processed_at IS NULL"),
                {"u": uid},
            )
        ).scalar_one()

    assert w < 0  # hides taught the model
    assert n_sugg == 1  # proposed once, not per event
    assert list(topic_exclude) == []  # NEVER the shared row
    assert list(personal) == []  # nothing without the user's yes
    assert unprocessed == 0  # watermark advanced


async def test_rerun_does_not_double_count() -> None:
    uid, story, _ = await _fixture()
    async with session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO events (user_id,story_id,kind,position)"
                " VALUES (:u,:st,'tapped_through',0)"
            ),
            {"u": uid, "st": story},
        )
    await learn.run(_job(uid))
    async with session_scope() as s:
        w1 = (
            await s.execute(
                text("SELECT value FROM weights WHERE user_id=:u AND kind='source' AND key='Ex'"),
                {"u": uid},
            )
        ).scalar_one()
    await learn.run(_job(uid))  # re-delivery: no unprocessed events left
    async with session_scope() as s:
        w2 = (
            await s.execute(
                text("SELECT value FROM weights WHERE user_id=:u AND kind='source' AND key='Ex'"),
                {"u": uid},
            )
        ).scalar_one()
    assert w1 == w2
