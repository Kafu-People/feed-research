"""Job postings seen on AI-data vendors' public job boards.

The earliest signal of a new earning opportunity is a vendor opening a role --
"AI Trainer, Rust", "Contributor, Brazilian Portuguese" -- before anyone posts
about it. Remembering what each board listed is what turns a daily fetch into
"what is new today".

Revision ID: a8b9c0d1e2f3
Revises: e7f8a9b0c1d2
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a8b9c0d1e2f3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_postings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        # "<ats>:<token>", e.g. "greenhouse:scaleai" -- one row per board.
        sa.Column("board", sa.Text(), nullable=False),
        sa.Column("ext_id", sa.Text(), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("location", sa.Text()),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("gone_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("board", "ext_id", name="uq_job_postings_board_ext"),
    )


def downgrade() -> None:
    op.drop_table("job_postings")
