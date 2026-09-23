"""brief_topics -- the user-managed list behind the daily Gemini brief.

A row is a named beat plus the prompt that researches it. Users own this list
from Slack (`/techtrend add|remove|list`), which is the point: the operator
should not have to edit a Python seed file to start watching a new niche.

Distinct from `topics`: a `topics` row is a keyword matcher run against the
crawled corpus, and a `brief_topics` row is a question put to a search engine.
They answer different halves of "what is happening with data annotation" --
what the press published, and what people actually said.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-09-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brief_topics",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        # Lowercased on the way in, so `/techtrend remove DataAnnotation`
        # finds what `/techtrend add dataannotation` created.
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        # Who asked for it. A list anyone can change needs to say who changed
        # it, or "why are we watching this?" has no answer.
        sa.Column("added_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        # Soft delete. `/techtrend remove` sets this false rather than
        # deleting, so the prompt survives a fat-fingered removal and
        # `last_run_at` still means something.
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("name", name="uq_brief_topics_name"),
    )
    op.create_index(
        "ix_brief_topics_active", "brief_topics", ["active"], postgresql_where=sa.text("active")
    )


def downgrade() -> None:
    op.drop_index("ix_brief_topics_active", table_name="brief_topics")
    op.drop_table("brief_topics")
