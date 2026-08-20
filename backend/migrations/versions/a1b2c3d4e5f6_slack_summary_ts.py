"""slack_posts.summary_ts -- the summary reply, addressable.

Without it, changing how summaries are formatted meant adding the
`channels:history` scope and walking `conversations.replies` just to FIND the
messages before they could be edited. The card's ts was recorded; the reply's
was not.

Revision ID: a1b2c3d4e5f6
Revises: f4a5b6c7d8e9
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("slack_posts", sa.Column("summary_ts", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("slack_posts", "summary_ts")
