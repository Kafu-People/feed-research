"""S3. Postgres stores a key, never the body (invariant #1)."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Any

import boto3

from techtrend.platform.config import settings


@lru_cache
def _s3() -> Any:
    s = settings()
    return boto3.client("s3", endpoint_url=s.s3_endpoint) if s.s3_endpoint else boto3.client("s3")


def text_key(url_hash: str) -> str:
    return f"text/{url_hash[:2]}/{url_hash}.txt"


def html_key(url_hash: str) -> str:
    return f"html/{url_hash[:2]}/{url_hash}.html"


def hash_url(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def put(key: str, body: str | bytes, content_type: str = "text/plain") -> str:
    data = body.encode() if isinstance(body, str) else body
    _s3().put_object(Bucket=settings().s3_bucket, Key=key, Body=data, ContentType=content_type)
    return key


def get(key: str) -> bytes:
    body: bytes = _s3().get_object(Bucket=settings().s3_bucket, Key=key)["Body"].read()
    return body
