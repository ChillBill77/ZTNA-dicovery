from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.db import init_engine, ping_db
from api.redis import init_redis, ping_redis
from api.settings import Settings


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = Settings()
    init_engine(settings)
    init_redis(settings)
    yield


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

    return app


app = build_app()
