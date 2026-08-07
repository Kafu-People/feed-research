"""PERSONAL layer tables. One user; reads the layers above, writes nothing outside."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Import downward so FK targets (topics, stories) exist in Base.metadata
# before mappers configure. personal -> topic -> shared is allowed.
import techtrend.topic.models  # noqa: F401
from techtrend.platform.db import Base


class EventKind(StrEnum):
    """Signals we collect, strongest first.

    NOTE the absence of a `CLICK` member. Invariant #8 says rank on tap-through
    and dwell, never raw clicks -- otherwise the ranking learns that outrage
    works. There is no member to accidentally start ranking on.
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


class SeenState(StrEnum):
    SHOWN = "shown"
    OPENED = "opened"
    TAPPED = "tapped"
    SKIPPED = "skipped"
    HIDDEN = "hidden"


class WeightKind(StrEnum):
    TYPE = "type"
    SOURCE = "source"
    KEYWORD = "keyword"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="UTC")
    digest_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="8")
    push_settings: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default='{"breaking": true, "max_per_day": 2}'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )
    label: Mapped[str | None] = mapped_column(Text)
    # "Just for me". NEVER writes to topics.exclude, which is shared.
    personal_excludes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Weight(Base):
    """The whole personal model: a few hundred interpretable numbers per user."""

    __tablename__ = "weights"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Seen(Base):
    __tablename__ = "seen"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    story_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str] = mapped_column(Text, nullable=False)
    # Recorded so position bias can be corrected. Without it the ranker
    # eventually learns "position 1 is good" and locks in what it believed.
    position: Mapped[int | None] = mapped_column(SmallInteger)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_user_recent", "user_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    story_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("stories.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Dismissal reason: the most valuable, rarest signal in the system.
    reason: Mapped[str | None] = mapped_column(Text)
    dwell_ms: Mapped[int | None] = mapped_column(BigInteger)
    position: Mapped[int | None] = mapped_column(SmallInteger)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Suggestion(Base):
    """Proposed topic changes. NEVER applied without the user accepting.

    This table exists so that `topics` is never written by a learning process
    (invariant #12).
    """

    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
