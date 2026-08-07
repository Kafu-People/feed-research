"""SHARED layer tables.

Computed once, identical for every user, forever. NOTE: no table here carries a
`user_id` -- that absence *is* invariant #11, and it is checkable by inspection.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from techtrend.platform.db import Base


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(String(1), nullable=False, server_default="C")
    country: Mapped[str | None] = mapped_column(String(2))
    language: Mapped[str | None] = mapped_column(Text)
    authority: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.5")
    paywall: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    robots_txt: Mapped[str | None] = mapped_column(Text)
    robots_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Publisher removal request. Gates collection AND serving (invariant #3).
    opt_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Endpoint(Base):
    __tablename__ = "endpoints"
    __table_args__ = (
        UniqueConstraint("site_id", "url"),
        # The scheduler's only hot query.
        Index(
            "ix_endpoints_due",
            "next_check_at",
            postgresql_where=("failure_streak < 10"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # feed | sitemap
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    # This column IS the scheduler. There is no scheduler process.
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    interval_s: Mapped[int] = mapped_column(Integer, nullable=False, server_default="600")
    quiet_streak: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    last_status: Mapped[int | None] = mapped_column(SmallInteger)
    failure_streak: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")


class Story(Base):
    __tablename__ = "stories"
    __table_args__ = (
        Index("ix_stories_unjudged", "created_at", postgresql_where=("judged_at IS NULL")),
        Index("ix_stories_subject", "subject_key", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    display_article_id: Mapped[int | None] = mapped_column(BigInteger)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    subject_key: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    story_type: Mapped[str | None] = mapped_column(Text)
    novelty_score: Mapped[float | None] = mapped_column(Float)
    hedge_score: Mapped[float | None] = mapped_column(Float)
    importance: Mapped[float | None] = mapped_column(Float)
    facts: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    judged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        Index("ix_articles_recent", "published_at"),
        Index("ix_articles_story", "story_id"),
        Index("ix_articles_site_day", "site_id", "published_at"),
        Index("ix_articles_ungrouped", "published_at", postgresql_where=("story_id IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sites.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # An S3 key. NEVER the body. Invariant #1 is enforced by the column's meaning.
    text_key: Mapped[str | None] = mapped_column(Text)
    html_key: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    author: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    entities: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    extraction: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    story_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("stories.id", ondelete="SET NULL")
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
