from redis.asyncio import Redis

IDEMPOTENCY_TTL = 86400  # 24시간


async def acquire(redis: Redis, key: str) -> bool:
    """Redis SET NX EX로 멱등성 키를 획득한다. True: 최초 처리, False: 중복."""
    result = await redis.set(
        f"idempotency:{key}",
        "1",
        ex=IDEMPOTENCY_TTL,
        nx=True,
    )
    return result is True
