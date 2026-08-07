"""TOPIC layer tables. Shared between users whose keyword lists are the same."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

# Downward import so the FK target `stories` is in Base.metadata.
import techtrend.shared.models  # noqa: F401
from techtrend.platform.db import Base


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # THE deduplication mechanism: normalise -> hash -> collide.
    # Ten thousand people typing a version of "AI news" collapse to one row.
    fingerprint: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    must: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    should: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    # SHARED across every subscriber. Personal narrowing goes in
    # subscriptions.personal_excludes instead -- confusing the two breaks #11/#12.
    exclude: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    entities: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    floor: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.35")
    subscriber_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    match_rate: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TopicTerm(Base):
    """The reverse index -- a search engine run backwards."""

    __tablename__ = "topic_terms"
    __table_args__ = (Index("ix_topic_terms_term", "term"),)

    term: Mapped[str] = mapped_column(Text, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (Index("ix_matches_topic_recent", "topic_id", "matched_at"),)

    topic_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )
    story_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True
    )
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Which keywords hit -> enables "less about price targets" on the card.
    matched_by: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
