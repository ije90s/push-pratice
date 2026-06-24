from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
from asyncpg import Pool

from app.core.config import settings

_pool: Pool | None = None


async def init_db() -> None:
    global _pool
    _pool = await asyncpg.create_pool(settings.database_url)


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> Pool:
    if _pool is None:
        raise RuntimeError("DB pool is not initialized")
    return _pool


@asynccontextmanager
async def lifespan_db():
    await init_db()
    try:
        yield
    finally:
        await close_db()


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    async with get_pool().acquire() as conn:
        yield conn
