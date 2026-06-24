from supabase import AsyncClient, acreate_client

from app.core.config import settings

_client: AsyncClient | None = None


async def init_db() -> None:
    global _client
    _client = await acreate_client(settings.supabase_url, settings.supabase_key)


async def close_db() -> None:
    global _client
    _client = None


def get_db() -> AsyncClient:
    if _client is None:
        raise RuntimeError("Supabase client is not initialized")
    return _client
