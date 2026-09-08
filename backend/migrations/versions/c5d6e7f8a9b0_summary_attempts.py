"""slack_posts.summary_attempts -- stop paying for a summary the model refuses.

The batch summariser reads `summary_ts IS NULL` as its work queue, which is
right for a transient failure and wrong for a permanent one. Roughly a third
of the first backlog came back declined -- the prompt's own SKIP hatch firing
on a paywall stub or a nav menu that survived extraction. Those rows keep
matching the queue, so they would be re-submitted every hour for as long as
the age window allows: 20 stories x 24 batches a day is more money wasted than
the batch discount saves.

A counter rather than a `declined_at` timestamp, because it also bounds the
other failure -- a story whose blob or Slack reply fails repeatedly.

Revision ID: c5d6e7f8a9b0
Revises: b2c3d4e5f6a7
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "slack_posts",
        sa.Column("summary_attempts", sa.SmallInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("slack_posts", "summary_attempts")
