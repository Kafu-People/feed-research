"""Topics: draft from a sentence, save, list, unsubscribe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, status
from sqlalchemy import delete, select, text

from techtrend.api.deps import SessionDep, UserDep
from techtrend.api.schemas import CardOut, TopicDraftIn, TopicDraftOut, TopicIn, TopicOut
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
    count, preview = await _dry_run(db, d.must, d.should, d.exclude, d.entities)
    return TopicDraftOut(
        title=d.title,
        must=d.must,
        should=d.should,
        entities=d.entities,
        exclude=d.exclude,
        ambiguity=d.ambiguity,
        options=d.options,
        count_7d=count,
        per_day=round(count / 7.0, 1),
        preview=preview,
    )


async def _dry_run(
    db: SessionDep,
    must: list[str],
    should: list[str],
    exclude: list[str],
    entities: list[str],
) -> tuple[int, list[CardOut]]:
    """Run the draft against the last 7 days with the SAME evaluate() the
    pipeline uses. If the preview used a different code path it would be a
    lie, and 'shows what we understood' would be worthless."""
    from techtrend.topic.match import StoryText, evaluate, searchable

    if not must:
        return 0, []
    since = datetime.now(UTC) - timedelta(days=7)
    rows = await db.execute(
        text("""
            SELECT st.id, a.title, a.description, a.entities, st.importance,
                   a.published_at, a.image_url, a.url, si.name, st.source_count
              FROM stories st
              JOIN articles a ON a.id = st.display_article_id
              JOIN sites si ON si.id = a.site_id
             WHERE a.published_at >= :since AND si.opt_out_at IS NULL
        """),
        {"since": since},
    )
    hits = []
    for r in rows:
        st = searchable(r[1], r[2], list(r[3] or []))
        score, _ = evaluate(
            must=must,
            should=should,
            exclude=exclude,
            entities=entities,
            topic_embedding=None,
            story=StoryText(text=st.text, embedding=None),
        )
        if score >= 0.35:
            hits.append((score * (r[4] or 0.5), r))
    hits.sort(key=lambda h: h[0], reverse=True)
    preview = [
        CardOut(
            story_id=r[0],
            headline=r[1],
            description=r[2],
            source_name=r[8],
            source_count=r[9],
            published_at=r[5],
            image_url=r[6],
            url=r[7],
        )
        for _, r in hits[:3]
    ]
    return len(hits), preview


@router.post("/topics", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
async def create_topic(body: TopicIn, user: UserDep, db: SessionDep) -> TopicOut:
    """Normalise -> hash -> collide.

    Ten thousand people typing some version of "AI news" collapse to a handful
    of rows: one matching job, ten thousand readers.
    """
    fp = fingerprint(body.must, body.should, body.entities, body.exclude)
    topic = await db.scalar(select(Topic).where(Topic.fingerprint == fp))
    if topic is None:
        from techtrend.shared.read.embed import embed_async
        from techtrend.topic.match import topic_embedding_input

        (vec,) = await embed_async(
            [topic_embedding_input(body.title, body.must, body.should, body.entities)]
        )
        topic = Topic(
            fingerprint=fp,
            title=body.title,
            must=body.must,
            should=body.should,
            entities=body.entities,
            exclude=body.exclude,
            embedding=vec,
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
    # Retro-match the recent corpus so the new topic's feed starts full --
    # committed with the subscription, worked by the match stage.
    from techtrend.platform import queue

    await queue.enqueue(
        "match", f"match:topic:{topic.id}", {"topic_id": topic.id}, session=db
    )
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
