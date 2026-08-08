"""HTTP request/response models.

Never serialise a SQLAlchemy model directly -- that is how article bodies leak.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field


class SuggestionOut(BaseModel):
    """A learned proposal. It changes nothing until the user accepts it."""

    id: int
    topic_id: int
    kind: str
    payload: dict[str, object]
    evidence: str | None = None


class TopicLabel(BaseModel):
    topic_id: int
    label: str


class CardOut(BaseModel):
    """One card on the dashboard.

    NOTE: there is no `text` / `body` field, and there never can be. Invariant #1
    -- headline + our own summary + thumbnail + link out, never the article body
    -- is enforced by the absence of somewhere to put one.
    """

    story_id: int
    headline: str
    summary: str | None = None  # null when unjudged: degrade, don't hide
    # The publisher's own preview snippet (og:description) -- shown QUOTED with
    # attribution when we have no summary of our own. Not the body.
    description: str | None = None
    source_name: str
    source_count: int
    published_at: datetime
    image_url: str | None = None
    url: str
    topic_labels: list[TopicLabel] = Field(default_factory=list)
    matched_by: list[str] = Field(default_factory=list)


class DashboardOut(BaseModel):
    cards: list[CardOut]
    generated_at: datetime
    done: bool = True  # "That's today." The bottom exists.
    more: list[CardOut] = Field(default_factory=list)


class TopicDraftIn(BaseModel):
    sentence: str = Field(min_length=3, max_length=500)


class TopicDraftOut(BaseModel):
    title: str
    must: list[str]
    should: list[str]
    entities: list[str]
    exclude: list[str]
    ambiguity: str | None = None
    options: list[str] = Field(default_factory=list)
    count_7d: int
    per_day: float
    preview: list[CardOut] = Field(default_factory=list)


class TopicIn(BaseModel):
    title: str
    must: list[str]
    should: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class TopicOut(BaseModel):
    id: int
    title: str
    must: list[str]
    should: list[str]
    entities: list[str]
    exclude: list[str]
    subscriber_count: int
    match_rate: float | None = None


class EventKindIn(StrEnum):
    """Mirrors personal.models.EventKind.

    There is no `click` member here either. Invariant #8: rank on tap-through
    and dwell, never raw clicks -- otherwise the ranking learns outrage works.
    """

    SHOWN = "shown"
    EXPANDED = "expanded"
    DWELL = "dwell"
    TAPPED_THROUGH = "tapped_through"
    SAVED = "saved"
    SHARED = "shared"
    SCROLLED_PAST = "scrolled_past"
    SKIPPED = "skipped"
    HIDDEN = "hidden"
    BEST_OF_DAY = "best_of_day"


class EventIn(BaseModel):
    story_id: int | None = None
    kind: EventKindIn
    reason: str | None = None
    dwell_ms: int | None = None
    position: int | None = None


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict[str, object] | None = None


class ErrorOut(BaseModel):
    error: ErrorBody


class HealthOut(BaseModel):
    status: str
    version: str
    env: str
