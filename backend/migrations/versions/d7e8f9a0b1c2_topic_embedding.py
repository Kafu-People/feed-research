"""topics.embedding -- vector recall for the matcher's paraphrase net.

Revision ID: d7e8f9a0b1c2
Revises: c4d5e6f7a8b9
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "d7e8f9a0b1c2"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("topics", sa.Column("embedding", Vector(384), nullable=True))
    # No HNSW index yet: topic counts are thousands at most for a long time,
    # and a sequential scan over thousands of vectors is microseconds.


def downgrade() -> None:
    op.drop_column("topics", "embedding")
