import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest
from supabase import acreate_client

from app.core.config import settings
from app.tasks.push import send_push_task


def _arun(coro):
    return asyncio.run(coro)


@pytest.fixture()
def pending_push_log():
    """retry → DEAD 흐름 검증용 push_log를 DB에 직접 삽입."""
    push_id = str(uuid.uuid4())
    key = str(uuid.uuid4())
    row = {
        "id": push_id,
        "idempotency_key": key,
        "title": "Crash 테스트",
        "content": "재시도 검증",
        "status": "PENDING",
        "success_count": 0,
        "failed_count": 0,
        "retry_count": 0,
    }

    async def _insert() -> None:
        db = await acreate_client(settings.supabase_url, settings.supabase_key)
        await db.table("push_logs").insert(row).execute()

    _arun(_insert())
    yield row

    async def _cleanup() -> None:
        db = await acreate_client(settings.supabase_url, settings.supabase_key)
        await db.table("push_logs").delete().eq("id", push_id).execute()

    _arun(_cleanup())


def test_worker_acks_late_configured() -> None:
    """acks_late=True 설정 확인 — 워커 crash 시 메시지 재전달 보장."""
    assert send_push_task.acks_late is True
    assert send_push_task.reject_on_worker_lost is True


def test_task_exhausts_retries_and_becomes_dead(pending_push_log: dict) -> None:
    """
    강제 실패(TASK_FAILURE_RATE=1.0) → max_retries 소진 → status=DEAD 검증.
    워커 crash 후 재시도 흐름과 동일한 retry 경로를 검증한다.
    NX 키는 항상 획득 성공으로 패치해 재시도가 중복으로 차단되지 않도록 한다.
    """
    push_id = pending_push_log["id"]
    key = pending_push_log["idempotency_key"]

    mock_redis = MagicMock()
    mock_redis.set.return_value = True  # NX 항상 획득 성공

    with patch("app.tasks.push.TASK_FAILURE_RATE", 1.0), \
         patch("app.tasks.push._get_redis", return_value=mock_redis):
        send_push_task.apply(args=[push_id, key, "Crash 테스트", "재시도 검증"])

    async def _check() -> dict:
        db = await acreate_client(settings.supabase_url, settings.supabase_key)
        res = await db.table("push_logs").select("*").eq("id", push_id).execute()
        return res.data[0]

    row = _arun(_check())
    assert row["status"] == "DEAD"
    assert row["retry_count"] == 3
    assert row["error_message"] is not None
    assert row["failed_at"] is not None
