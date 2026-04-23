from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.settings import Settings

_engine = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> None:
    global _engine, _session_maker  # noqa: PLW0603 — module-level singletons
    _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    _session_maker = async_sessionmaker(_engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    if _session_maker is None:
        raise RuntimeError("DB engine not initialised; call init_engine first")
    async with _session_maker() as session:
        yield session


async def ping_db() -> bool:
    if _engine is None:
        return False
    try:
        async with _engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False
