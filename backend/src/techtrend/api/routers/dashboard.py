"""The one screen: cards from all topics, mixed, best first, each labelled."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import select, text

from techtrend.api.deps import SessionDep, UserDep
from techtrend.api.schemas import CardOut, DashboardOut, TopicLabel
from techtrend.personal.models import Seen, Weight
from techtrend.personal.rank import Candidate, Weights, rank, select_dashboard
from techtrend.platform.config import settings

router = APIRouter(tags=["dashboard"])

# Candidates = matches for the user's subscribed topics, minus what they've seen,
# minus opted-out publishers (invariant #3 gates serving, not just collection).
_CANDIDATES = text("""
    SELECT st.id, a.title, st.summary, si.name, si.id, st.source_count,
           a.published_at, a.image_url, a.url, st.importance,
           m.match_score, t.id, COALESCE(sub.label, t.title), m.matched_by,
           COALESCE(st.story_type, 'analysis'), a.description, sub.personal_excludes
      FROM matches m
      JOIN subscriptions sub ON sub.topic_id = m.topic_id AND sub.user_id = :uid
      JOIN topics  t  ON t.id  = m.topic_id
      JOIN stories st ON st.id = m.story_id
      JOIN articles a ON a.id  = st.display_article_id
      JOIN sites   si ON si.id = a.site_id
     WHERE si.opt_out_at IS NULL
       AND st.importance IS NOT NULL
       AND NOT EXISTS (
             SELECT 1 FROM seen s
              WHERE s.user_id = :uid AND s.story_id = st.id
           )
     ORDER BY st.importance DESC
     LIMIT 400
""")


async def _load_weights(db: SessionDep, user_id: int) -> Weights:
    rows = await db.execute(select(Weight).where(Weight.user_id == user_id))
    w = Weights()
    for row in rows.scalars():
        {"type": w.by_type, "source": w.by_source, "keyword": w.by_keyword}[row.kind][row.key] = (
            row.value
        )
    return w


def _to_card(c: Candidate) -> CardOut:
    return CardOut(
        story_id=c.story_id,
        headline=c.headline,
        summary=c.summary,
        description=c.description,
        source_name=c.source_name,
        source_count=c.source_count,
        published_at=c.published_at,
        image_url=c.image_url,
        url=c.url,
        topic_labels=[TopicLabel(topic_id=c.topic_id, label=lbl) for lbl in c.topic_labels],
        matched_by=c.matched_by,
    )


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(user: UserDep, db: SessionDep) -> DashboardOut:
    from techtrend.topic.match import _hit as term_hits  # noqa: PLC2701
    from techtrend.topic.match import searchable

    rows = await db.execute(_CANDIDATES, {"uid": user.id})
    candidates = [
        Candidate(
            story_id=r[0],
            headline=r[1],
            summary=r[2],
            source_name=r[3],
            source_id=r[4],
            source_count=r[5],
            published_at=r[6],
            image_url=r[7],
            url=r[8],
            importance=r[9],
            match_score=r[10],
            topic_id=r[11],
            topic_label=r[12],
            matched_by=list(r[13] or []),
            story_type=r[14],
            description=r[15],
        )
        for r in rows
        # The user's own narrowing of a shared topic (invariant #12's pressure
        # valve): an accepted personal exclude filters HERE, per subscription.
        if not any(term_hits(term, searchable(r[1], r[15], []).text) for term in (r[16] or []))
    ]

    weights = await _load_weights(db, user.id)
    ranked = rank(candidates, weights, now=datetime.now(UTC))

    s = settings()
    picked = select_dashboard(ranked, s.dashboard_max_cards, s.exploration_slots)
    picked_ids = {c.story_id for c in picked}
    cards = [_to_card(c) for c in picked]
    more = [_to_card(c) for c in ranked if c.story_id not in picked_ids][:10]

    # Record position so bias can be corrected later.
    for i, c in enumerate(cards):
        await db.merge(Seen(user_id=user.id, story_id=c.story_id, state="shown", position=i))
    await db.commit()

    # NOTE: no backfill. If there are seven good things, seven is what ships
    # (invariant #10). That is also what keeps every skip a clean negative.
    return DashboardOut(cards=cards, generated_at=datetime.now(UTC), done=True, more=more)
