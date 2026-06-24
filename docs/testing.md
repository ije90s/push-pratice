# 테스트

## 전략 개요

| 레이어 | 도구 | 필수 여부 | 목적 |
|---|---|---|---|
| 단위 테스트 | pytest | **필수** | services, celery tasks 비즈니스 로직 검증 |
| 통합 테스트 | pytest + testcontainers | 선택 | 실제 Redis/PostgreSQL 연동 검증 |
| E2E 테스트 | httpx AsyncClient | **필수 (핵심만)** | 주요 엔드포인트 흐름 검증 |

## 실행 명령

```bash
uv run pytest                                          # 전체 테스트
uv run pytest tests/unit/                              # 단위 테스트만
uv run pytest tests/integration/                       # 통합 테스트만
uv run pytest -k "test_idempotency"                    # 특정 테스트 이름 매칭
uv run pytest -v --tb=short                            # 상세 출력
uv run pytest --cov=app --cov-report=term-missing      # 커버리지
uv run pytest --html=report.html --self-contained-html # HTML 리포트 생성
```

## 단위 테스트

외부 의존성(Redis, DB)은 모두 mock 처리한다. Fake FCM은 내부 랜덤 로직이므로 별도 mock 없이 결과값을 제어한다.

### 멱등성 서비스

```python
async def test_duplicate_key_skips_processing(mock_redis):
    mock_redis.set.return_value = False  # 키 이미 존재

    result = await idempotency_service.acquire("existing-key")

    assert result is False
    mock_redis.set.assert_called_once()
```

### 재시도 로직

```python
def test_retry_with_exponential_backoff(celery_app, mocker):
    mock_fake_fcm = mocker.patch("app.tasks.push.fake_fcm.send")
    mock_fake_fcm.side_effect = Exception("simulated failure")

    with pytest.raises(Retry) as exc_info:
        send_push_task.apply(args=[payload])

    assert exc_info.value.countdown == 60  # 1차 재시도 60초
```

### Fake FCM 성공/실패 제어

```python
@pytest.mark.parametrize("success_rate,expected_status", [
    (1.0, "SENT"),   # 항상 성공
    (0.0, "FAILED"), # 항상 실패 → retry
])
async def test_fake_fcm_result(success_rate, expected_status, mocker):
    mocker.patch("app.tasks.push.FAKE_FCM_SUCCESS_RATE", success_rate)
    ...
```

## 통합 테스트

실제 Redis와 PostgreSQL을 사용해 상태 전이와 멱등성을 검증한다.

`testcontainers`를 사용해 테스트 실행 시 컨테이너를 자동으로 기동/종료한다.

```python
@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer() as redis:
        yield redis

@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16") as pg:
        yield pg
```

### 멱등성 통합 테스트

```python
async def test_same_key_processed_once(redis_client, db_pool):
    key = "idempotent-key-001"

    result1 = await process_push(payload, idempotency_key=key)
    result2 = await process_push(payload, idempotency_key=key)

    assert result1.status == "SENT"
    assert result2.status == "DUPLICATE"

    rows = await db_pool.fetch("SELECT * FROM push_logs WHERE idempotency_key = $1", key)
    assert len(rows) == 1  # DB에 단 1건만 기록
```

### DLQ 통합 테스트

```python
async def test_max_retry_moves_to_dlq(db_pool, mocker):
    mocker.patch("app.tasks.push.FAKE_FCM_SUCCESS_RATE", 0.0)  # 항상 실패

    await send_push_task.apply_async(args=[payload])
    # 3회 재시도 소진 시뮬레이션
    ...

    row = await db_pool.fetchrow(
        "SELECT * FROM push_logs WHERE id = $1", push_id
    )
    assert row["status"] == "DEAD"
    assert row["failed_at"] is not None

    dlq_rows = await db_pool.fetch(
        "SELECT * FROM push_logs WHERE status = 'DEAD'"
    )
    assert len(dlq_rows) == 1
```

## E2E 테스트

FastAPI `TestClient` (비동기: `httpx.AsyncClient`)로 HTTP 레이어부터 검증한다.

```python
@pytest.mark.anyio
async def test_push_endpoint_returns_202(async_client, mock_celery):
    response = await async_client.post("/push", json={
        "title": "테스트",
        "content": "내용",
    })

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    mock_celery.send_task.assert_called_once()


@pytest.mark.anyio
async def test_dlq_list(async_client, db_pool):
    # push_logs에 DEAD 상태 데이터 삽입
    await db_pool.execute(
        "INSERT INTO push_logs (..., status) VALUES (..., 'DEAD')"
    )

    response = await async_client.get("/dlq?limit=20&offset=0")

    assert response.status_code == 200
    assert response.json()["total"] >= 1


@pytest.mark.anyio
async def test_dlq_retry(async_client, mock_celery, db_pool):
    response = await async_client.post(f"/dlq/{idempotency_key}/retry")

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    mock_celery.send_task.assert_called_once()
```

## 테스트 파일 구조

```
tests/
├── conftest.py            # 공통 fixture (컨테이너, DB 풀, 클라이언트)
├── unit/
│   ├── test_idempotency.py
│   ├── test_push_task.py
│   └── test_fake_fcm.py
├── integration/
│   ├── test_push_flow.py
│   └── test_dlq.py
└── e2e/
    ├── test_push_api.py
    └── test_dlq_api.py
```
