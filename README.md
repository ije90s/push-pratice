# push-practice

> FastAPI + Celery + Redis 기반 멀티 워커 환경에서 **멱등성**과 **DLQ**를 고려한 비동기 푸시 처리 시스템

Node.js + SQS로 구현했던 단일 워커 푸시 시스템을 Python으로 재구현하며, 멀티 워커 확장 시 발생하는 중복 처리·메시지 유실 문제를 해결하는 것을 목표로 한다.

---

## 배경

### v1 한계 (Node.js + SQS)

- 단일 워커 구조 → 멀티 워커 확장 불가
- Visibility Timeout 초과 시 중복 처리 발생
- Worker crash 시 메시지 유실 가능성

### v2 해결 전략 (Python + Celery)

| 문제 | 해결 |
|---|---|
| 중복 처리 | Redis 기반 멱등성 키 (`SET NX EX`) |
| 메시지 유실 | `acks_late=True` + DLQ (`push_logs.status = 'DEAD'`) |
| 단일 워커 | Celery 멀티 워커 |

---

## 기술 스택

| 역할 | 기술 |
|---|---|
| API 서버 | FastAPI |
| 비동기 처리 | Celery |
| 메시지 브로커 | Redis (DB0) |
| 멱등성 저장소 | Redis (DB2) |
| 영구 저장소 | Supabase (PostgreSQL) |
| 워커 모니터링 | Flower |
| 패키지 관리 | uv |
| 린트/포맷 | ruff |
| 테스트 | pytest |
| 부하 테스트 | Locust |

---

## 아키텍처

```
Client ──▶ FastAPI ──▶ Redis (Broker)
               │              │
          push_logs        dequeue
          INSERT             │
          (PENDING)     Celery Workers
                             │
                    Redis (Dedup) ──▶ idempotency check
                             │
                    Fake FCM (랜덤 성공/실패)
                    100건 청크 + 30ms 송신 제어
                             │
                    push_logs UPDATE
                    (SENT / DEAD)
```

**FCM은 실제 호출 없이 Fake로 동작한다.** 랜덤 성공/실패를 시뮬레이션하여 멱등성·재시도·DLQ 흐름을 검증한다.

---

## 핵심 기능

### 멱등성

```
SET idempotency:{key} "1" EX 86400 NX
```

Worker 처리 시작 전 Redis에 atomic하게 키를 설정한다. 키가 이미 존재하면 중복으로 판단하고 즉시 종료한다.

### DLQ

별도 Redis List 없이 `push_logs.status = 'DEAD'`를 DLQ로 사용한다.

- max_retries(3) 초과 → `status = 'DEAD'`, `failed_at` 기록
- 재처리: `POST /dlq/{idempotency_key}/retry` → `status = 'PENDING'` + re-enqueue

### 재시도 (지수 백오프)

| 시도 | 대기 시간 |
|---|---|
| 1차 | 60초 |
| 2차 | 120초 |
| 3차 | 240초 |
| 초과 | DLQ |

---

## 시작하기

### 사전 준비

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (Redis 실행용)
- Supabase 프로젝트 (또는 로컬 PostgreSQL)

### 환경 설정

```bash
cp .env.example .env
# .env에 SUPABASE_URL, SUPABASE_KEY, REDIS_URL 등 설정
```

### Redis 실행

```bash
docker run -d -p 6379:6379 redis:7
```

### 앱 실행

```bash
uv run fastapi dev app/main.py                                        # FastAPI 개발 서버 (포트 8000)
uv run celery -A app.worker worker --loglevel=info                    # Celery 워커 실행 (별도 터미널)
uv run celery -A app.worker worker --loglevel=info --concurrency=4    # 멀티 워커 실행 (concurrency=4)
uv run celery -A app.worker flower --port=5500                        # Flower 모니터링
```

---

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/push` | 전체 유저 대상 푸시 전송 요청 |
| `GET` | `/push/{push_id}` | 푸시 상태 조회 |
| `GET` | `/dlq` | DLQ 목록 조회 |
| `POST` | `/dlq/{idempotency_key}/retry` | DLQ 메시지 재처리 |

- Base URL: `http://localhost:8000`
- Flower: `http://localhost:5500`

자세한 명세는 [`docs/api.md`](docs/api.md)를 참조한다.

---

## 테스트

```bash
uv run pytest                                           # 전체
uv run pytest tests/unit/                               # 단위 (services, celery tasks)
uv run pytest tests/e2e/                                # E2E
uv run pytest --html=report.html --self-contained-html  # HTML 리포트
uv run locust -f locustfile.py                          # 부하 테스트 (웹 UI: localhost:8089)
uv run locust -f locustfile.py --headless -u 100 -r 10  # 부하 테스트 (CLI)
```

---

## 문서

| 문서 | 내용 |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | 전체 아키텍처 및 이벤트 흐름 |
| [`docs/api.md`](docs/api.md) | API 명세 |
| [`docs/database.md`](docs/database.md) | DB 스키마 및 Redis 키 설계 |
| [`docs/messaging.md`](docs/messaging.md) | Celery 설정 및 멱등성/DLQ 처리 |
| [`docs/push.md`](docs/push.md) | Fake FCM 동작 및 전송 흐름 |
| [`docs/testing.md`](docs/testing.md) | 테스트 전략 및 예시 |
