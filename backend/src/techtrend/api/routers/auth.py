from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from techtrend.api.deps import SessionDep, hash_password, issue_token, verify_password
from techtrend.api.schemas import SignupIn, TokenOut
from techtrend.personal.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenOut, status_code=201)
async def signup(body: SignupIn, db: SessionDep) -> TokenOut:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error": {"code": "email_taken", "message": "email already registered"}},
        )
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token, ttl = issue_token(user.id)
    return TokenOut(access_token=token, expires_in=ttl)


@router.post("/login", response_model=TokenOut)
async def login(body: SignupIn, db: SessionDep) -> TokenOut:
    user = await db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "invalid credentials"}},
        )
    token, ttl = issue_token(user.id)
    return TokenOut(access_token=token, expires_in=ttl)
