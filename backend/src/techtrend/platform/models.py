"""The jobs table. Infrastructure, not domain -- hence it lives in platform/."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from techtrend.platform.db import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # Enqueue twice is a no-op rather than double work.
        UniqueConstraint("stage", "key", name="uq_jobs_stage_key"),
        # Partial: finished jobs leave the index immediately, so it stays
        # roughly the size of the pending backlog.
        Index(
            "ix_jobs_claimable",
            "stage",
            "priority",
            "run_after",
            postgresql_where=("state = 'pending'"),
        ),
        Index("ix_jobs_stuck", "locked_at", postgresql_where=("state = 'running'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="100")
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="5")
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
