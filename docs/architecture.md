# 아키텍처

## 전체 구조

```
┌─────────────┐     HTTP      ┌─────────────┐     enqueue     ┌──────────────────────┐
│   Client    │ ──────────▶   │   FastAPI   │ ─────────────▶  │  Redis DB0 (Broker)  │
└─────────────┘               └─────────────┘                  └──────────┬───────────┘
                                     │                                     │
                                     │ INSERT push_logs (PENDING)          │ dequeue
                                     ▼                                     ▼
                              ┌─────────────┐               ┌─────────────────────────┐
                              │  PostgreSQL  │               │     Celery Workers      │
                              │  push_logs  │               │   (multi-worker pool)   │
                              └──────┬──────┘               └──────────┬──────────────┘
                                     │                                  │
                                     │ UPDATE status                    │ SET NX EX
                                     │ (SENT / DEAD)                    ▼
                                     │                    ┌─────────────────────────┐
                                     │                    │  Redis DB2 (Dedup)      │
                                     │                    │  idempotency:{key} = 1  │
                                     │                    └──────────┬──────────────┘
                                     │                               │
                                     │                               │ FCM call (chunked)
                                     │                               ▼
                                     │                    ┌─────────────────────────┐
                                     │                    │    Firebase FCM(FAKE)         │
                                     │                    │  (전체 유저 배치 전송)    │
                                     │                    └──────────┬──────────────┘
                                     │                               │ max_retries 초과
                                     └───────────────────────────────┘
                                          status = 'DEAD' (DLQ)
```

## 컴포넌트 역할
| 컴포넌트 | 역할 |
|---|---|
| **FastAPI** | HTTP 수신, 입력 유효성 검사, `push_logs` PENDING 기록, Celery 태스크 enqueue |
| **Redis DB0** | Celery 태스크 큐 브로커 |
| **Redis DB1** | Celery 태스크 결과 백엔드 (임시 저장소) |
| **Redis DB2** | 멱등성 키 저장소 (`idempotency:{key}`, TTL 24시간) |
| **Celery Worker** | 멱등성 확인 → 전체 유저 조회 → 청크 + 송신 제어 + FAKE FCM 전송 → DB 상태 업데이트 |
| **PostgreSQL** | `push_logs` 영구 저장, DLQ(`status = 'DEAD'`) 역할 겸임 |
| **FCM** | Fake 디바이스 푸시 전송 (랜덤 성공/실패 시뮬레이션) |

## 이벤트 흐름

```
[1] API 수신
  POST /push { title, content, idempotency_key? }
  └── idempotency_key 없으면 UUID 발급
  └── push_logs INSERT (status = PENDING)
  └── Celery에 태스크 enqueue (랜덤 성공/실패 시뮬레이션)
      ├── enqueue 실패 → 500 응답, DB PENDING 유지 (재요청 필요)
      └── enqueue 성공 → 202 Accepted { push_id, idempotency_key, status }

[2] Worker 처리
  dequeue
  └── Redis DB2: SET idempotency:{key} NX EX 86400
      ├── SET 실패 (키 존재) → 중복, ack 후 종료
      └── SET 성공 → push_logs.send_at 기록, status = PENDING 유지
           └── 태스크 처리 랜덤 실패 시뮬레이션 (20%)
               ├── 실패 + retries < max_retries → retry 스케줄, retry_count/error_message 기록
               └── 실패 + retries >= max_retries → status = DEAD, failed_at 기록 (DLQ)
           └── (성공 시) users 테이블 전체 조회
               └── 100건 청크 + 30ms 송신 제어
                   └── Fake FCM 전송 (랜덤 성공/실패)
                       ├── 성공 → success_count 누적
                       └── 실패 → failed_count 누적 (retry 없음, 이미 전송 처리)
           └── 전송 완료 → status = SENT, completed_at 기록, ack

[3] 재시도 / DLQ
  태스크 처리 랜덤 실패 → Celery retry (지수 백오프: 60s → 120s → 240s)
  └── retries >= max_retries(3) 도달 시
      └── push_logs UPDATE: status = DEAD, failed_at 기록 후 종료
          → push_logs WHERE status = 'DEAD' 가 DLQ
  ※ FCM 성공/실패는 retry 대상 아님 (카운트만 기록)

[4] DLQ 재처리
  POST /dlq/{idempotency_key}/retry
  └── push_logs UPDATE: status = PENDING
  └── Celery re-enqueue
  └── 202 Accepted { push_id, status: "PENDING" }
```

## 핵심 설계 원칙

### 1. 멱등성 (Idempotency)
- Worker 처리 시작 전 Redis DB2에서 `SET idempotency:{key} "1" EX 86400 NX` (atomic)
- SET 실패 → 중복 요청, 즉시 종료 (ack)
- SET 성공 → 최초 처리, 진행

### 2. 메시지 유실 방지
- `acks_late=True`: 태스크 완료 후 ack → Worker crash 시 재처리 보장
- `reject_on_worker_lost=True`: Worker 강제 종료 시 메시지 requeue
- max_retries 초과 시 `push_logs.status = 'DEAD'`로 유실 없이 영구 보관

### 3. DLQ
- 별도 Redis List 없이 `push_logs.status = 'DEAD'`를 DLQ로 사용
- `push_logs`에 이미 `title`, `content`, `idempotency_key`, `error_message`가 있어 별도 페이로드 저장 불필요
- Redis 재시작과 무관하게 영구 보관

### 4. Massive Push
- 1건의 `push_logs` 레코드 = 전체 유저(`users` 테이블) 대상 푸시 1회 실행
- 개별 유저 단위 기록 없음; 집계 카운트(`success_count`, `failed_count`)로 결과 추적
- 푸시 처리 순서: 전체 조회 > 청크 + 송신 제어 > Fake FCM 전송(건바이건으로 랜덤으로 성공/실패)

## 디렉토리 구조

```
push-pratice/
├── app/
│   ├── api/           # FastAPI 라우터 (push, dlq)
│   ├── core/          # 설정, 의존성 (DB, Redis 커넥션)
│   ├── schemas/       # Pydantic 요청/응답 스키마
│   ├── services/      # 비즈니스 로직 (push 서비스, 멱등성 서비스)
│   ├── tasks/         # Celery 태스크 정의
│   └── worker.py      # Celery 앱 초기화
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── docs/
├── main.py
└── pyproject.toml
```
