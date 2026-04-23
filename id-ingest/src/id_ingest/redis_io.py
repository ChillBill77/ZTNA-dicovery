from __future__ import annotations

from ztna_common.redis_bus import RedisStreamProducer

IDENTITY_STREAM = "identity.events"


def make_producer(redis_url: str) -> RedisStreamProducer:
    return RedisStreamProducer(redis_url, stream=IDENTITY_STREAM)
