import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import settings

_redis: Redis | None = None


async def init_redis() -> None:
    global _redis
    _redis = aioredis.from_url(settings.redis_idempotency_url, decode_responses=True)


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis client is not initialized")
    return _redis
