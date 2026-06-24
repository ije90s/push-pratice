import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from supabase import acreate_client

from app.core.config import settings
from app.main import app


def _arun(coro):
    return asyncio.run(coro)


@pytest.fixture()
def e2e_client(mocker):
    mocker.patch("app.api.push.send_push_task.delay")
    mocker.patch("app.api.dlq.send_push_task.delay")
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def cleanup_push_ids():
    ids: list[str] = []
    yield ids

    async def _cleanup() -> None:
        db = await acreate_client(settings.supabase_url, settings.supabase_key)
        for push_id in ids:
            await db.table("push_logs").delete().eq("id", push_id).execute()

    _arun(_cleanup())


@pytest.fixture()
def dead_push_row(e2e_client) -> dict:
    push_id = str(uuid.uuid4())
    idempotency_key = str(uuid.uuid4())
    row = {
        "id": push_id,
        "idempotency_key": idempotency_key,
        "title": "E2E 제목",
        "content": "E2E 내용",
        "status": "DEAD",
        "success_count": 0,
        "failed_count": 0,
        "retry_count": 3,
        "error_message": "처리 실패",
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
