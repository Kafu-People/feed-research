"""daily_digests -- the durable memory of which days have been reported.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-01

The queue cannot serve as this memory: `purge_done` deletes finished job rows,
so a purge followed by a sweep inside the same local day would re-enqueue the
same digest and post it twice. Same reasoning as `slack_posts`.

Keyed on the LOCAL day (a plain date, not a timestamp), because "the 1st of
September in Sao Paulo" is the thing that must happen once -- and that is not
expressible as a UTC instant without re-deriving the offset every time.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_digests",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("ts", sa.Text(), nullable=False),
        sa.Column("story_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "posted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("day", "channel"),
    )


def downgrade() -> None:
    op.drop_table("daily_digests")
