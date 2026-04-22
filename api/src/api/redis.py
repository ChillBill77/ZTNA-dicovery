from __future__ import annotations

from redis.asyncio import Redis

from api.settings import Settings

_client: Redis | None = None


def init_redis(settings: Settings) -> None:
    global _client
    _client = Redis.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> Redis:
    if _client is None:
        raise RuntimeError("Redis client not initialised; call init_redis first")
    return _client


async def ping_redis() -> bool:
    if _client is None:
        return False
    try:
        return bool(await _client.ping())
    except Exception:  # noqa: BLE001
        return False
