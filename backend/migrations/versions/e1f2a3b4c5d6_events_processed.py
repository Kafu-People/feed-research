"""events.processed_at -- the learning worker's exactly-once watermark.

Revision ID: e1f2a3b4c5d6
Revises: d7e8f9a0b1c2
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "CREATE INDEX ix_events_unprocessed ON events (user_id, id)"
        " WHERE processed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_events_unprocessed", table_name="events")
    op.drop_column("events", "processed_at")
