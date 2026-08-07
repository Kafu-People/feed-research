"""Integration conftest: a real Postgres, migrated, truncated between tests."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from collections.abc import AsyncIterator

import pytest

TEST_DB = os.environ.get(
    "TT_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:dev@localhost:5432/techtrend_test",
)


def pg_available() -> bool:
    try:
        with socket.create_connection(("localhost", 5432), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not pg_available(), reason="Postgres not running")


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> None:
    if not pg_available():
        pytest.skip("Postgres not running")

    import psycopg

    name = TEST_DB.rsplit("/", 1)[-1]
    admin = TEST_DB.replace("+asyncpg", "").rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')

    os.environ["TT_DATABASE_URL"] = TEST_DB
    from techtrend.platform.config import settings

    settings.cache_clear()

    # sys.executable -m alembic: the console script may not be on PATH.
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "TT_DATABASE_URL": TEST_DB},
    )


@pytest.fixture(autouse=True)
async def clean_db(migrated_db: None) -> AsyncIterator[None]:
    """Truncate before, dispose after.

    Disposal matters: pytest-asyncio gives each test its own event loop, and a
    pooled asyncpg connection opened on a closed loop raises
    `RuntimeError: Event loop is closed`. Fresh pool per test.
    """
    from sqlalchemy import text

    from techtrend.platform.db import dispose, session_scope

    async with session_scope() as s:
        await s.execute(
            text(
                "TRUNCATE jobs, events, seen, weights, subscriptions, suggestions,"
                " matches, topic_terms, topics, articles, stories, endpoints,"
                " sites, users RESTART IDENTITY CASCADE"
            )
        )
    try:
        yield
    finally:
        await dispose()
