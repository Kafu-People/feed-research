"""Auth, sessions, current user."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from techtrend.personal.models import User
from techtrend.platform.config import settings
from techtrend.platform.db import sessionmaker


async def session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as s:
        yield s


SessionDep = Annotated[AsyncSession, Depends(session)]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(user_id: int) -> tuple[str, int]:
    """Minimal HS256-style JWT. Real deployments swap in a vetted library."""
    ttl = settings().access_token_ttl_s
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = {"sub": str(user_id), "exp": int(time.time()) + ttl}
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = hmac.new(
        settings().jwt_secret.get_secret_value().encode(), signing_input, hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{_b64(sig)}", ttl


def verify_token(token: str) -> int:
    try:
        header, payload, sig = token.split(".")
    except ValueError:
        raise _unauthorized() from None
    expected = hmac.new(
        settings().jwt_secret.get_secret_value().encode(),
        f"{header}.{payload}".encode(),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(_unb64(sig), expected):
        raise _unauthorized()
    body: dict[str, Any] = json.loads(_unb64(payload))
    if int(body.get("exp", 0)) < time.time():
        raise _unauthorized("token expired")
    return int(body["sub"])


def _unauthorized(msg: str = "invalid credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": "unauthorized", "message": msg}},
        headers={"WWW-Authenticate": "Bearer"},
    )


# Public-board mode: accounts are switched off "for now". Every request acts
# as the one shared board user, so the dashboard, topics, and feeds are the
# same for everyone. The token machinery above stays for the day accounts
# return; nothing below reads the Authorization header.
PUBLIC_EMAIL = "board@techtrend.local"


async def current_user(
    db: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    user = await db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        # Not a credential: an unloginable sentinel (no auth route exists).
        user = User(email=PUBLIC_EMAIL, password_hash="!public-board-no-login")  # noqa: S106
        db.add(user)
        await db.commit()
    return user


UserDep = Annotated[User, Depends(current_user)]


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or hashlib.sha256(str(time.time_ns()).encode()).digest()[:16]
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2$200000${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_b64, dk_b64 = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt_b64), int(iters))
        return hmac.compare_digest(dk, _unb64(dk_b64))
    except (ValueError, TypeError):
        return False
