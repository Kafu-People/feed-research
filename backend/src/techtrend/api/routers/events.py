"""Feedback. Batched, fire-and-forget: never block a UI transition on this."""

from __future__ import annotations

from fastapi import APIRouter, status

from techtrend.api.deps import SessionDep, UserDep
from techtrend.api.schemas import EventIn
from techtrend.personal.models import Event, Seen

router = APIRouter(tags=["feedback"])

# state written to `seen` for each event kind, where it implies one
_SEEN_STATE = {
    "tapped_through": "tapped",
    "expanded": "opened",
    "skipped": "skipped",
    "hidden": "hidden",
}


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def post_events(batch: list[EventIn], user: UserDep, db: SessionDep) -> dict[str, int]:
    for e in batch:
        db.add(
            Event(
                user_id=user.id,
                story_id=e.story_id,
                kind=e.kind.value,
                reason=e.reason,
                dwell_ms=e.dwell_ms,
                position=e.position,
            )
        )
        state = _SEEN_STATE.get(e.kind.value)
        if state and e.story_id is not None:
            await db.merge(
                Seen(user_id=user.id, story_id=e.story_id, state=state, position=e.position)
            )
    # Weight updates run in a worker, coalesced per user -- a skip must not
    # cost learning work on the interactive path. Enqueued with the events,
    # in the same transaction.
    from techtrend.personal.learn import enqueue_for

    await enqueue_for(user.id, session=db)
    await db.commit()
    return {"accepted": len(batch)}
