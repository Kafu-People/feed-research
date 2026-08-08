"""Suggestions: proposed by learning, applied only by the user.

Invariant #12 lives here. The learning worker may notice a pattern, but
nothing changes a user's topic without asking -- and an accepted personal
exclude lands in subscriptions.personal_excludes, never in the shared
topics.exclude (invariant #11).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from techtrend.api.deps import SessionDep, UserDep
from techtrend.api.schemas import SuggestionOut
from techtrend.personal.models import Subscription, Suggestion

router = APIRouter(tags=["suggestions"])


@router.get("/suggestions", response_model=list[SuggestionOut])
async def list_suggestions(user: UserDep, db: SessionDep) -> list[SuggestionOut]:
    rows = await db.execute(
        select(Suggestion).where(Suggestion.user_id == user.id, Suggestion.state == "pending")
    )
    return [
        SuggestionOut(
            id=s.id,
            topic_id=s.topic_id,
            kind=s.kind,
            payload=dict(s.payload),
            evidence=s.evidence,
        )
        for s in rows.scalars()
    ]


async def _load(db: SessionDep, user_id: int, suggestion_id: int) -> Suggestion:
    s = await db.scalar(
        select(Suggestion).where(
            Suggestion.id == suggestion_id,
            Suggestion.user_id == user_id,
            Suggestion.state == "pending",
        )
    )
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no such pending suggestion")
    return s


@router.post("/suggestions/{suggestion_id}/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept(suggestion_id: int, user: UserDep, db: SessionDep) -> None:
    s = await _load(db, user.id, suggestion_id)
    if s.kind == "personal_exclude":
        sub = await db.scalar(
            select(Subscription).where(
                Subscription.user_id == user.id, Subscription.topic_id == s.topic_id
            )
        )
        term = str(s.payload.get("term", ""))
        if sub is not None and term and term not in sub.personal_excludes:
            # THE user's subscription row -- the shared topic is untouched.
            sub.personal_excludes = [*sub.personal_excludes, term]
    s.state = "accepted"
    await db.commit()


@router.post("/suggestions/{suggestion_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss(suggestion_id: int, user: UserDep, db: SessionDep) -> None:
    s = await _load(db, user.id, suggestion_id)
    s.state = "dismissed"
    await db.commit()
