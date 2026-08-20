"""slack_posts -- the durable memory of what has been announced.

The jobs table dedups in-flight work only; `purge_done` deletes those rows
after a day. Without this table, a queue purge would re-announce the corpus.

Revision ID: f4a5b6c7d8e9
Revises: e1f2a3b4c5d6
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_posts",
        sa.Column("story_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("ts", sa.Text(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "posted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("story_id", "channel"),
    )


def downgrade() -> None:
    op.drop_table("slack_posts")
