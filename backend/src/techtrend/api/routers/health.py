from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from techtrend import __version__
from techtrend.api.deps import SessionDep
from techtrend.api.schemas import HealthOut
from techtrend.platform.config import settings

router = APIRouter(tags=["ops"])


@router.get("/healthz", response_model=HealthOut)
async def healthz() -> HealthOut:
    """Liveness: the process is up. No dependencies checked."""
    return HealthOut(status="ok", version=__version__, env=settings().env)


@router.get("/readyz", response_model=HealthOut)
async def readyz(db: SessionDep) -> HealthOut:
    """Readiness: dependencies reachable. Fails -> the rollout stalls rather
    than replacing good instances with broken ones."""
    await db.execute(text("SELECT 1"))
    return HealthOut(status="ready", version=__version__, env=settings().env)


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
