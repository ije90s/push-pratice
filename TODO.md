# 구현 TODO

- 각 항목은 1 커밋 단위다.
- 각 단계의 할일이 제대로 되는지 확인하고, 완료됐으면, 체크로 변경한다.

## 의존성 순서

```
패키지 의존성 → 스캐폴딩 → 설정/DB/Redis → Celery
→ 스키마 → 멱등성 서비스 → Fake FCM → Celery 태스크
→ Push API → DLQ API → 앱 진입점
→ 단위 테스트 → E2E 테스트
```

---

## 1단계 — 프로젝트 기반

- [x] **패키지 의존성 추가**
  - `pyproject.toml`: celery, redis, supabase, pydantic-settings, python-dotenv, pytest, pytest-asyncio, pytest-mock, pytest-html 추가
  - `.env.example` 작성 (SUPABASE_URL, SUPABASE_KEY, REDIS_URL, FAKE_FCM_SUCCESS_RATE 등)

- [x] **디렉토리 스캐폴딩**
  - `app/api/`, `app/core/`, `app/schemas/`, `app/services/`, `app/tasks/` 생성 + `__init__.py`
  - `tests/unit/`, `tests/integration/`, `tests/e2e/` 생성 + `conftest.py`, `__init__.py`

---

## 2단계 — 인프라 연결

- [x] **설정 로드** (`app/core/config.py`)
  - pydantic-settings로 `.env` 로드
  - SUPABASE_URL, SUPABASE_KEY, REDIS_URL, FAKE_FCM_SUCCESS_RATE, CELERY_BROKER_URL, CELERY_RESULT_BACKEND

- [x] **DB 연결** (`app/core/database.py`)
  - supabase-py AsyncClient
  - init_db/close_db로 FastAPI lifespan 관리

- [x] **Redis 연결** (`app/core/redis.py`)
  - DB2 (idempotency) 클라이언트 설정
  - DB0/DB1은 Celery 설정에서 직접 사용

- [x] **Celery 앱 초기화** (`app/worker.py`)
  - broker: Redis DB0, result_backend: Redis DB1
  - `acks_late=True`, `reject_on_worker_lost=True`, `task_acks_on_failure_or_timeout=False`
  - `task_serializer=json`

---

## 3단계 — 핵심 로직

- [x] **Pydantic 스키마** (`app/schemas/push.py`, `app/schemas/dlq.py`)
  - `PushRequest`: title, content, idempotency_key?
  - `PushResponse`: push_id, idempotency_key, status
  - `PushStatusResponse`: 전체 push_logs 필드
  - `DlqListResponse`: items, total
  - `DlqRetryResponse`: push_id, status

- [x] **멱등성 서비스** (`app/services/idempotency.py`)
  - `SET idempotency:{key} "1" EX 86400 NX` 원자 연산
  - acquire(key) → bool (True: 최초, False: 중복)

- [x] **Fake FCM** (`app/services/fake_fcm.py`)
  - `FAKE_FCM_SUCCESS_RATE = 0.9` (환경변수로 조정)
  - `fake_fcm_send(token, title, content) -> bool`

- [x] **Celery 태스크** (`app/tasks/push.py`)
  - 멱등성 확인 → 중복 시 ack 후 종료
  - users 전체 조회
  - 100건 청크 + 30ms 송신 제어
  - Fake FCM 전송 → success_count / failed_count 누적
  - 전송 완료 → status=SENT, completed_at 기록
  - 실패 → retry (60s → 120s → 240s)
  - max_retries(3) 초과 → status=DEAD, failed_at 기록

---

## 4단계 — API 레이어

- [x] **앱 진입점** (`app/main.py`)
  - FastAPI 인스턴스, lifespan 등록
  - 라우터 등록 (push, dlq)
  - 공통 에러 핸들러

- [x] **Push API** (`app/api/push.py`)
  - `POST /push`: idempotency_key 서버에서 UUID 발급 → push_logs INSERT(PENDING) → Celery enqueue → 201
  - `GET /push/{push_id}`: push_logs 조회 → 200

- [x] **DLQ API** (`app/api/dlq.py`)
  - `GET /dlq?limit=20&offset=0`: push_logs WHERE status='DEAD' 조회
  - `POST /dlq/{idempotency_key}/retry`: Redis 멱등성 키 삭제 → status=PENDING 업데이트 → Celery re-enqueue → 201

---

## 5단계 — 테스트

- [x] **단위 테스트 — 멱등성** (`tests/unit/test_idempotency.py`) **[필수]**
  - 신규 키 → True 반환
  - 중복 키 → False 반환

- [x] **단위 테스트 — Celery 태스크** (`tests/unit/test_push_task.py`) **[필수]**
  - 멱등성 중복 시 태스크 조기 종료 검증
  - 재시도 지수 백오프 (1차 60s) 검증
  - max_retries 초과 시 status=DEAD 검증

- [x] **단위 테스트 — Fake FCM** (`tests/unit/test_fake_fcm.py`) **[필수]**
  - success_rate=1.0 → 항상 True
  - success_rate=0.0 → 항상 False

- [x] **E2E 테스트 — Push API** (`tests/e2e/test_push_api.py`) **[필수]**
  - POST /push → 201, status=PENDING
  - GET /push/{push_id} → 200

- [x] **E2E 테스트 — DLQ API** (`tests/e2e/test_dlq_api.py`) **[필수]**
  - GET /dlq → 200, DEAD 항목 반환
  - POST /dlq/{key}/retry → 201, status=PENDING

---

## 6단계 — E2E 테스트 (추가)

- [x] **멱등성 동시성** (`tests/e2e/test_idempotency_concurrency.py`)
  - 같은 `idempotency_key`로 동시에 N개 요청 발사
  - push_logs 1건만 생성됐는지 확인
  - Celery 태스크도 1번만 실행됐는지 확인

- [x] **워커 crash 복구** (`tests/e2e/test_worker_crash.py`)
  - 태스크 처리 중 워커 `kill -9`
  - `acks_late=True`로 태스크 재큐잉 확인
  - 재시도 후 SENT 또는 max_retries 초과 시 DEAD 확인

---
