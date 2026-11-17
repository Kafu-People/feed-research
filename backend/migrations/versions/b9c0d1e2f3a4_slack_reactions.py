"""👍 / 👎 reactions on stories in #feed-ai-news.

Each edition's thread has one reply per story, so a reaction on a reply names
exactly one story. The story's category and publisher are copied onto the row
when it is recorded: the ranking boost reads "how does the team feel about
funding news, about this publisher" without re-deriving either.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-11-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_reactions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("story_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        # +1 for 👍, -1 for 👎.
        sa.Column("vote", sa.SmallInteger(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("site_id", sa.BigInteger()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("story_id", "user_id", "vote", name="uq_slack_reactions_vote"),
    )
    op.create_index("ix_slack_reactions_created", "slack_reactions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_slack_reactions_created", table_name="slack_reactions")
    op.drop_table("slack_reactions")
