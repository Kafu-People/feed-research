"""articles.description -- the publisher's own preview snippet.

The 1-2 sentence text publishers put in JSON-LD / og:description precisely so
other sites can show it in link previews. Not the body (invariant #1); the
card may quote it with attribution until our own summaries exist.

Revision ID: c4d5e6f7a8b9
Revises: 8b1f4a9c2d3e
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "8b1f4a9c2d3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "description")
