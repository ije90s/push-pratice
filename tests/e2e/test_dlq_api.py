from fastapi.testclient import TestClient


def test_list_dlq_returns_dead_items(e2e_client: TestClient, dead_push_row: dict) -> None:
    res = e2e_client.get("/dlq")

    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    ids = [item["id"] for item in body["items"]]
    assert dead_push_row["id"] in ids


def test_retry_dlq_returns_200(e2e_client: TestClient, dead_push_row: dict) -> None:
    res = e2e_client.post(f"/dlq/{dead_push_row['idempotency_key']}/retry")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "PENDING"
    assert body["push_id"] == dead_push_row["id"]


def test_retry_dlq_updates_db_status(e2e_client: TestClient, dead_push_row: dict) -> None:
    e2e_client.post(f"/dlq/{dead_push_row['idempotency_key']}/retry")

    get_res = e2e_client.get(f"/push/{dead_push_row['id']}")

    assert get_res.status_code == 200
    assert get_res.json()["status"] == "PENDING"


def test_retry_dlq_not_found(e2e_client: TestClient) -> None:
    res = e2e_client.post("/dlq/00000000-0000-0000-0000-000000000000/retry")

    assert res.status_code == 404
