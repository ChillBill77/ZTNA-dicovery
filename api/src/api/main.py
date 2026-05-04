from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.auth.router import router as auth_router
from api.db import init_engine, ping_db
from api.logging_config import configure_logging
from api.metrics import MetricsMiddleware, metrics_endpoint
from api.middleware_csrf import CsrfMiddleware
from api.redis import init_redis, ping_redis
from api.routers import (
    adapters,
    applications,
    flows,
    groups,
    identity,
    saas,
    ws,
)
from api.routers.ws import shutdown as ws_shutdown
from api.routers.ws import startup as ws_startup
from api.settings import Settings


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.log_level)
    init_engine(settings)
    init_redis(settings)
    await ws_startup()
    try:
        yield
    finally:
        await ws_shutdown()


def build_app() -> FastAPI:
    app = FastAPI(title="ZTNA Discovery API", lifespan=_lifespan)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        db_ok = await ping_db()
        redis_ok = await ping_redis()
        healthy = db_ok and redis_ok
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "status": "ok" if healthy else "degraded",
                "components": {"db": db_ok, "redis": redis_ok},
            },
        )

    app.add_middleware(MetricsMiddleware)
    app.add_middleware(CsrfMiddleware)

    app.get("/metrics", include_in_schema=False)(metrics_endpoint)

    app.include_router(auth_router)
    app.include_router(flows.router)
    app.include_router(applications.router)
    app.include_router(saas.router)
    app.include_router(adapters.router)
    app.include_router(identity.router)
    app.include_router(groups.router)
    app.include_router(ws.router)

    # Test-only routes — enabled only when MOCK_SESSION=1. CI E2E uses these
    # to mint session cookies + publish synthetic SankeyDeltas without driving
    # the real OIDC flow. Never enable in production.
    settings = Settings()
    if settings.mock_session_enabled:
        import json
        import secrets
        import time

        from api.auth.session import SessionCodec, SessionData
        from api.redis import get_redis

        @app.post("/api/test/login-as", include_in_schema=False)
        async def _test_login_as(payload: dict[str, Any]) -> dict[str, str]:
            csrf = secrets.token_urlsafe(8)
            codec = SessionCodec(settings.session_secret)
            token = codec.encode(
                SessionData(
                    user_upn=payload["upn"],
                    roles=set(payload["roles"]),
                    csrf=csrf,
                    exp=int(time.time()) + 3600,
                )
            )
            return {"session": token, "csrf_token": csrf}

        @app.post("/api/test/seed", include_in_schema=False)
        async def _test_seed(payload: dict[str, Any]) -> dict[str, bool]:
            await get_redis().publish("sankey.live", json.dumps(payload))
            return {"ok": True}

    # When the web SPA has been bundled into /app/web-dist, serve it at root.
    # In dev the separate Vite server replaces this behavior.
    web_dist = Path("/app/web-dist")
    if web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")

    return app


app = build_app()
