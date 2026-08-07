"""pgvector: embedding columns on articles and stories, HNSW cosine indexes.

Revision ID: 8b1f4a9c2d3e
Revises: 3c50da021d64
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "8b1f4a9c2d3e"
down_revision = "3c50da021d64"
branch_labels = None
depends_on = None

DIMS = 384  # semi-permanent; see shared/read/embed.py


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("articles", sa.Column("embedding", Vector(DIMS), nullable=True))
    op.add_column("stories", sa.Column("embedding", Vector(DIMS), nullable=True))
    # HNSW over cosine distance -- Group's candidate retrieval is the hot path.
    op.execute(
        "CREATE INDEX ix_articles_embedding ON articles"
        " USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX ix_stories_embedding ON stories"
        " USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.drop_index("ix_articles_embedding", table_name="articles")
    op.drop_index("ix_stories_embedding", table_name="stories")
    op.drop_column("articles", "embedding")
    op.drop_column("stories", "embedding")
