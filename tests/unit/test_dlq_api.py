from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.redis import get_redis
from app.main import app

_DEAD_ROW = {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "idempotency_key": "dead-key",
    "title": "제목",
    "content": "내용",
    "retry_count": 3,
    "error_message": "처리 실패",
    "failed_at": "2026-06-24T00:00:00+00:00",
    "created_at": "2026-06-24T00:00:00+00:00",
    "status": "DEAD",
    "success_count": 0,
    "failed_count": 0,
    "send_at": None,
    "completed_at": None,
}


def _make_mock_db(rows: list | None = None, count: int = 0):
    mock_db = MagicMock()

    list_execute = AsyncMock(return_value=MagicMock(data=rows or []))
    count_execute = AsyncMock(return_value=MagicMock(count=count))

    # list_dlq: .select().eq().range().execute() 와 .select(count=exact).eq().execute()
    range_mock = MagicMock()
    range_mock.execute = list_execute

    eq_for_list = MagicMock()
    eq_for_list.range.return_value = range_mock
    eq_for_list.execute = count_execute

    select_mock = MagicMock()
    select_mock.eq.return_value = eq_for_list

    mock_db.table.return_value.select.return_value = select_mock

    # retry: .select().eq("idempotency_key", ...).eq("status", ...).execute()
    # eq_for_list 는 첫 번째 .eq() 반환값이므로, 두 번째 .eq()도 AsyncMock execute 연결
    eq_for_list.eq.return_value.execute = AsyncMock(return_value=MagicMock(data=rows or []))

    # .update().eq().execute()
    update_eq = MagicMock()
    update_eq.execute = AsyncMock(return_value=MagicMock())

    update_mock = MagicMock()
    update_mock.eq.return_value = update_eq

    mock_db.table.return_value.update.return_value = update_mock

    return mock_db


def _make_client(mocker, rows=None, count=0):
    mock_db = _make_mock_db(rows=rows, count=count)
    mock_redis = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: mock_redis

    mocker.patch("app.api.dlq.send_push_task.delay")

    return mock_db, mock_redis


def test_list_dlq_returns_200(mocker):
    _make_client(mocker, rows=[_DEAD_ROW], count=1)

    with TestClient(app) as c:
        res = c.get("/dlq")

    app.dependency_overrides.clear()

    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["idempotency_key"] == "dead-key"


def test_list_dlq_empty(mocker):
    _make_client(mocker, rows=[], count=0)

    with TestClient(app) as c:
        res = c.get("/dlq")

    app.dependency_overrides.clear()

    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0}


def test_retry_dlq_returns_201(mocker):
    _make_client(mocker, rows=[_DEAD_ROW], count=1)

    with TestClient(app) as c:
        res = c.post("/dlq/dead-key/retry")

    app.dependency_overrides.clear()

    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "PENDING"
    assert "push_id" in body


def test_retry_dlq_not_found(mocker):
    _make_client(mocker, rows=[], count=0)

    with TestClient(app) as c:
        res = c.post("/dlq/nonexistent-key/retry")

    app.dependency_overrides.clear()

    assert res.status_code == 404