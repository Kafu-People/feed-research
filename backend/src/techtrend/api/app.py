"""FastAPI app factory. Thin: HTTP shape, auth, serialisation.

No ranking or matching logic lives here -- that is personal/rank.py and
topic/match.py, so both stay unit-testable without HTTP and neither can grow a
second implementation inside a request handler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from techtrend import __version__
from techtrend.api.routers import auth, dashboard, events, health, suggestions, topics
from techtrend.platform import cache, db, telemetry
from techtrend.platform.config import check_production_invariants, settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    s = settings()
    telemetry.init(s.env, s.log_level)
    check_production_invariants(s)
    telemetry.log.info("api.boot", env=s.env, version=__version__, model=s.ai_model)
    yield
    await cache.close()
    await db.dispose()


def create_app() -> FastAPI:
    s = settings()
    app = FastAPI(
        title="TechTrend API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # Web is served on the apex domain with the API at api.* -- same parent
    # domain keeps the refresh cookie first-party. Local dev needs explicit CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"] if s.env == "local" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/v1")
    app.include_router(topics.router, prefix="/v1")
    app.include_router(dashboard.router, prefix="/v1")
    app.include_router(events.router, prefix="/v1")
    app.include_router(suggestions.router, prefix="/v1")

    @app.exception_handler(500)
    async def on_error(_: Request, exc: Exception) -> JSONResponse:
        telemetry.log.exception("api.unhandled", error=repr(exc))
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal", "message": "internal error"}},
        )

    return app


app = create_app()
