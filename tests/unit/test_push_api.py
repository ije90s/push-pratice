import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
from app.core.redis import get_redis


def _make_mock_db(row: dict | None = None):
    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute = AsyncMock(return_value=MagicMock())
    mock_db.table.return_value.select.return_value.eq.return_value.execute = AsyncMock(
        return_value=MagicMock(data=[row] if row else [])
    )
    return mock_db


@pytest.fixture()
def client(mocker):
    mock_db = _make_mock_db(row={
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "idempotency_key": "test-key",
        "title": "제목",
        "content": "내용",
        "success_count": 0,
        "failed_count": 0,
        "status": "PENDING",
        "retry_count": 0,
        "error_message": None,
        "created_at": "2026-06-24T00:00:00+00:00",
        "send_at": None,
        "completed_at": None,
        "failed_at": None,
    })
    mock_redis = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: mock_redis

    mocker.patch("app.api.push.send_push_task.delay")

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def test_post_push_returns_201(client):
    res = client.post("/push", json={"title": "제목", "content": "내용"})

    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "PENDING"
    assert "push_id" in body
    assert "idempotency_key" in body


def test_post_push_generates_idempotency_key(client):
    res = client.post("/push", json={"title": "제목", "content": "내용"})

    assert res.status_code == 201
    assert res.json()["idempotency_key"] != ""


def test_get_push_returns_200(client):
    res = client.get("/push/550e8400-e29b-41d4-a716-446655440000")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "PENDING"
    assert body["title"] == "제목"


def test_get_push_not_found(mocker):
    mock_db = _make_mock_db(row=None)
    mock_redis = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: mock_redis

    with TestClient(app) as c:
        res = c.get("/push/non-existent-id")

    app.dependency_overrides.clear()

    assert res.status_code == 404
