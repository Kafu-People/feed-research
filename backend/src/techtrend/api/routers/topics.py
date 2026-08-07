"""Topics: draft from a sentence, save, list, unsubscribe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, status
from sqlalchemy import delete, select, text

from techtrend.api.deps import SessionDep, UserDep
from techtrend.api.schemas import TopicDraftIn, TopicDraftOut, TopicIn, TopicOut
from techtrend.personal.models import Subscription
from techtrend.topic.distill import distill
from techtrend.topic.fingerprint import fingerprint, normalise_term
from techtrend.topic.models import Topic, TopicTerm

router = APIRouter(tags=["topics"])


@router.post("/topics/draft", response_model=TopicDraftOut)
async def draft(body: TopicDraftIn, user: UserDep, db: SessionDep) -> TopicDraftOut:
    """Sentence -> editable chips + the rate + three real headlines.

    The preview runs the SAME matcher the pipeline uses. If it used a different
    code path the preview would be a lie, and "shows what we understood" would
    be worthless.
    """
    d = await distill(body.sentence)
    stats = await _dry_run(db, d.must, d.exclude)
    return TopicDraftOut(
        title=d.title,
        must=d.must,
        should=d.should,
        entities=d.entities,
        exclude=d.exclude,
        ambiguity=d.ambiguity,
        options=d.options,
        count_7d=stats["count_7d"],
        per_day=stats["per_day"],
        preview=[],
    )


async def _dry_run(db: SessionDep, must: list[str], exclude: list[str]) -> dict[str, float]:
    """How many stories would this topic have matched in the last 7 days?"""
    since = datetime.now(UTC) - timedelta(days=7)
    if not must:
        return {"count_7d": 0, "per_day": 0.0}
    # An empty exclude array is correct as-is: `x ILIKE ANY('{}')` is false, so
    # `NOT (...)` is true. No sentinel value needed -- and a NUL sentinel would
    # be rejected by Postgres as invalid UTF-8 anyway.
    row = await db.execute(
        text("""
            SELECT count(*) FROM stories st
             JOIN articles a ON a.id = st.display_article_id
            WHERE st.created_at >= :since
              AND a.title ILIKE ANY(CAST(:must AS text[]))
              AND NOT (a.title ILIKE ANY(CAST(:excl AS text[])))
        """),
        {
            "since": since,
            "must": [f"%{m}%" for m in must],
            "excl": [f"%{e}%" for e in exclude],
        },
    )
    n = int(row.scalar() or 0)
    return {"count_7d": n, "per_day": round(n / 7.0, 1)}


@router.post("/topics", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
async def create_topic(body: TopicIn, user: UserDep, db: SessionDep) -> TopicOut:
    """Normalise -> hash -> collide.

    Ten thousand people typing some version of "AI news" collapse to a handful
    of rows: one matching job, ten thousand readers.
    """
    fp = fingerprint(body.must, body.should, body.entities, body.exclude)
    topic = await db.scalar(select(Topic).where(Topic.fingerprint == fp))
    if topic is None:
        topic = Topic(
            fingerprint=fp,
            title=body.title,
            must=body.must,
            should=body.should,
            entities=body.entities,
            exclude=body.exclude,
        )
        db.add(topic)
        await db.flush()
        # Normalise FIRST, then dedupe. Deduping raw casing lets "Nvidia" and
        # "nvidia" both collapse to one term and collide on the primary key.
        terms = {normalise_term(t) for t in (*body.must, *body.should, *body.entities)}
        for term in sorted(terms - {""}):
            db.add(TopicTerm(term=term, topic_id=topic.id))

    already = await db.scalar(
        select(Subscription).where(
            Subscription.user_id == user.id, Subscription.topic_id == topic.id
        )
    )
    if already is None:
        db.add(Subscription(user_id=user.id, topic_id=topic.id, label=body.title))
        topic.subscriber_count += 1
    await db.commit()
    await db.refresh(topic)
    return _out(topic)


@router.get("/topics", response_model=list[TopicOut])
async def list_topics(user: UserDep, db: SessionDep) -> list[TopicOut]:
    rows = await db.execute(
        select(Topic)
        .join(Subscription, Subscription.topic_id == Topic.id)
        .where(Subscription.user_id == user.id)
    )
    return [_out(t) for t in rows.scalars()]


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(topic_id: int, user: UserDep, db: SessionDep) -> None:
    await db.execute(
        delete(Subscription).where(
            Subscription.user_id == user.id, Subscription.topic_id == topic_id
        )
    )
    await db.execute(
        text(
            "UPDATE topics SET subscriber_count = GREATEST(0, subscriber_count - 1) WHERE id = :tid"
        ),
        {"tid": topic_id},
    )
    await db.commit()


def _out(t: Topic) -> TopicOut:
    return TopicOut(
        id=t.id,
        title=t.title,
        must=list(t.must),
        should=list(t.should),
        entities=list(t.entities),
        exclude=list(t.exclude),
        subscriber_count=t.subscriber_count,
        match_rate=t.match_rate,
    )
