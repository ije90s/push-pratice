import pytest
from unittest.mock import AsyncMock

from app.services.idempotency import acquire, IDEMPOTENCY_TTL


@pytest.mark.asyncio
async def test_acquire_new_key_returns_true():
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True

    result = await acquire(mock_redis, "new-key")

    assert result is True
    mock_redis.set.assert_called_once_with(
        "idempotency:new-key", "1", ex=IDEMPOTENCY_TTL, nx=True
    )


@pytest.mark.asyncio
async def test_acquire_duplicate_key_returns_false():
    mock_redis = AsyncMock()
    mock_redis.set.return_value = None  # Redis SET NX 실패 시 None 반환

    result = await acquire(mock_redis, "existing-key")

    assert result is False
