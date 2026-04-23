from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.auth.router import router as auth_router
from api.db import init_engine, ping_db
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

    app.add_middleware(CsrfMiddleware)

    app.include_router(auth_router)
    app.include_router(flows.router)
    app.include_router(applications.router)
    app.include_router(saas.router)
    app.include_router(adapters.router)
    app.include_router(identity.router)
    app.include_router(groups.router)
    app.include_router(ws.router)

    # When the web SPA has been bundled into /app/web-dist, serve it at root.
    # In dev the separate Vite server replaces this behavior.
    web_dist = Path("/app/web-dist")
    if web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")

    return app


app = build_app()
