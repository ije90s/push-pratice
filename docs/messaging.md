# 메시징

## 개요

v1(Node.js + SQS)의 단일 워커 한계를 극복하기 위해 **Celery + Redis** 기반 멀티 워커 큐 시스템으로 재설계한다.

## 이벤트 흐름

```
[1] API 수신
  POST /push
  └── idempotency_key 생성 (없으면 UUID 발급)
  └── DB에 PENDING 기록
  └── Celery에 태스크 enqueue (랜덤 성공/실패 시뮬레이션)
      ├── enqueue 실패 → 500 응답, DB PENDING 유지 (재요청 필요)
      └── enqueue 성공 → 202 Accepted 응답

[2] Worker 처리
  dequeue
  └── Redis에서 idempotency_key 존재 확인
      ├── 존재 → 중복 처리, 태스크 종료 (ack)
      └── 없음 → Redis에 키 SET (TTL 설정)
           └── send_at 기록
           └── 태스크 처리 랜덤 실패 시뮬레이션 (20%)
               ├── 실패 + retries < max_retries → retry 스케줄 (지수 백오프)
               └── 실패 + retries >= max_retries → DB DEAD 업데이트 (DLQ), 종료
           └── (성공 시) users 전체 조회 → 100건 청크 → 30ms 송신 제어
               └── Fake FCM 전송 (랜덤 성공/실패)
                   ├── 성공 → success_count 누적
                   └── 실패 → failed_count 누적 (retry 없음)
           └── 전송 완료 → DB SENT 업데이트, ack
```

## Celery 설정

### 핵심 옵션

| 옵션 | 값 | 이유 |
|---|---|---|
| `acks_late` | `True` | 처리 완료 후 ack → worker crash 시 재처리 보장 |
| `reject_on_worker_lost` | `True` | worker 강제 종료 시 메시지 requeue |
| `task_acks_on_failure_or_timeout` | `False` | 실패 시 nack → retry 가능하게 |
| `task_serializer` | `json` | 직렬화 형식 |
| `result_backend` | Redis | 태스크 결과 저장 |

### 재시도 전략 (지수 백오프)

```python
@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    reject_on_worker_lost=True,
)
def send_push_task(self, payload: dict):
    try:
        ...
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)
```

| 시도 | 대기 시간 |
|---|---|
| 1차 재시도 | 60초 |
| 2차 재시도 | 120초 |
| 3차 재시도 | 240초 |
| 초과 | DLQ 이동 |

## 멱등성 처리

```
Redis Key: idempotency:{idempotency_key}
Value:     "1"
TTL:       86400 (24시간)
```

- `SET key value EX ttl NX` 명령 사용: 키가 없을 때만 SET 성공 (atomic)
- SET 성공 → 최초 처리, 진행
- SET 실패 (키 존재) → 중복 요청, 즉시 종료

## Dead Letter Queue (DLQ)

max_retries 초과 시 `push_logs.status = 'DEAD'`로 업데이트한다.

- 별도 Redis List 없이 PostgreSQL을 DLQ로 사용
- `push_logs`에 이미 `title`, `content`, `idempotency_key`, `error_message`가 있어 별도 페이로드 저장 불필요
- 조회: `SELECT * FROM push_logs WHERE status = 'DEAD'`
- 재처리: `status → PENDING` 업데이트 후 Celery re-enqueue

## v1(SQS) vs v2(Celery) 비교

| 항목 | v1 (Node.js + SQS) | v2 (Python + Celery) |
|---|---|---|
| 워커 수 | 단일 | 멀티 |
| 중복 방지 | Visibility Timeout 의존 | Redis 멱등성 키 |
| 메시지 유실 대응 | 이중 로그 기록 | acks_late + DLQ |
| 재시도 | SQS 내장 | Celery retry (지수 백오프) |
| DLQ | SQS DLQ | PostgreSQL (`status = 'DEAD'`) |
| FCM 전송 | 실제 FCM | Fake FCM (랜덤 시뮬레이션) |
