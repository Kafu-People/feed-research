"""DELIVER layer tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, PrimaryKeyConstraint, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from techtrend.platform.db import Base


class SlackPost(Base):
    """The durable record that a story has been announced.

    The jobs table dedups in-flight work, but `purge_done` eventually deletes
    those rows -- so the job queue cannot be the memory of what was posted.
    This table is. Without it, a queue purge re-announces the whole corpus.
    """

    __tablename__ = "slack_posts"
    __table_args__ = (PrimaryKeyConstraint("story_id", "channel"),)

    story_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stories.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    # Slack's message id, and the parent for follow-up replies in-thread.
    ts: Mapped[str] = mapped_column(Text, nullable=False)
    # Source count as of the last message sent about this story; a later merge
    # raising it above this is what earns a threaded follow-up.
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # The threaded summary reply, when one was posted. NULL means a guard
    # declined it (thin extraction, no body, model returned SKIP) -- which is a
    # normal outcome, not a failure. Recorded so a future reformat can address
    # the message directly instead of scanning the thread for it.
    summary_ts: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
