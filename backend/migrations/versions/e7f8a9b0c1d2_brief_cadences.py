"""Per-cadence run stamps -- the same topic, asked three different questions.

A watchlist topic is not one question. "What is happening with AI training
work" means something different depending on when you ask it: today it means
what broke overnight, this week it means what moved, this month it means the
state of the field. The first research topic added here proved the point --
a 17,542-character overview, perfect once, and identical if you ask again
tomorrow.

So the cadence is not a property the user picks between. Every topic runs at
all three, and each run is stamped separately, because "did we do the weekly
one yet" cannot be answered by a single `last_run_at`.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `last_run_at` stays the daily stamp: it already means that, and
    # renaming it would break nothing except every query that reads it.
    op.add_column("brief_topics", sa.Column("last_weekly_at", sa.DateTime(timezone=True)))
    op.add_column("brief_topics", sa.Column("last_monthly_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("brief_topics", "last_monthly_at")
    op.drop_column("brief_topics", "last_weekly_at")
