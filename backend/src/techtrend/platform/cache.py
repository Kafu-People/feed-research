"""Redis: today's dashboards, seen sets, rate limits. Rebuildable from Postgres."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from techtrend.platform.config import settings

_client: aioredis.Redis | None = None


def client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(settings().redis_url, decode_responses=True)
    return _client


def dashboard_key(user_id: int) -> str:
    return f"dash:{user_id}"


async def get_json(key: str) -> Any | None:
    raw = await client().get(key)
    return json.loads(raw) if raw else None


async def put_json(key: str, value: Any, ttl: int = 300) -> None:
    await client().set(key, json.dumps(value, default=str), ex=ttl)


async def drop(key: str) -> None:
    await client().delete(key)


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
