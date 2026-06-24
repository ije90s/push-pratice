from fastapi.testclient import TestClient


def test_create_push_returns_201(e2e_client: TestClient, cleanup_push_ids: list[str]) -> None:
    res = e2e_client.post("/push", json={"title": "E2E 제목", "content": "E2E 내용"})

    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "PENDING"
    assert "push_id" in body
    assert "idempotency_key" in body
    cleanup_push_ids.append(body["push_id"])


def test_create_push_persisted_to_db(e2e_client: TestClient, cleanup_push_ids: list[str]) -> None:
    create_res = e2e_client.post("/push", json={"title": "E2E 제목", "content": "E2E 내용"})
    assert create_res.status_code == 201
    push_id = create_res.json()["push_id"]
    cleanup_push_ids.append(push_id)

    get_res = e2e_client.get(f"/push/{push_id}")

    assert get_res.status_code == 200
    body = get_res.json()
    assert body["id"] == push_id
    assert body["status"] == "PENDING"
    assert body["title"] == "E2E 제목"


def test_get_push_not_found(e2e_client: TestClient) -> None:
    res = e2e_client.get("/push/00000000-0000-0000-0000-000000000000")

    assert res.status_code == 404
