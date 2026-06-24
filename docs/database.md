# 데이터베이스

## 개요

영구 저장소로 **superbase(PostgreSQL)**, 임시 키/큐 저장소로 **Redis**를 사용한다.

---

## PostgreSQL 테이블

### `users` — 유저 정보

```sql
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_token  TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### `push_logs` — massive push job 이력

한 레코드 = 전체 유저 대상 푸시 1회 실행 단위

```sql
CREATE TYPE push_status AS ENUM ('PENDING', 'SENT', 'FAILED', 'DEAD');

CREATE TABLE push_logs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key   VARCHAR(255) NOT NULL UNIQUE,
    title             TEXT NOT NULL,
    content           TEXT NOT NULL,
    success_count     INT NOT NULL DEFAULT 0,   -- FCM 전송 성공 수
    failed_count      INT NOT NULL DEFAULT 0,   -- FCM 전송 실패 수
    status            push_status NOT NULL DEFAULT 'PENDING',
    retry_count       INT NOT NULL DEFAULT 0,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    send_at           TIMESTAMPTZ,               -- 전송 시작 시각
    completed_at      TIMESTAMPTZ,               -- 전송 완료 시각
    failed_at         TIMESTAMPTZ                -- DLQ 이동 시각 (max_retries 초과)
);
```

---

## Redis 키 설계

### 멱등성 키

```
Key:   idempotency:{idempotency_key}
Type:  String
Value: "1"
TTL:   86400 (24시간)
SET 전략: SET NX EX  (atomic)
```

### Celery 브로커/결과

```
Broker:  redis://localhost:6379/0   #워커 생성
Backend: redis://localhost:6379/1   #임시 저장소
Dedup:   redis://localhost:6379/2   #멱등성 확인
```
- DB 인덱스를 분리하여 Celery 내부 키와 애플리케이션 키가 충돌하지 않도록 한다.

### DLQ

별도 Redis List를 두지 않고, `push_logs.status = 'DEAD'`를 DLQ로 사용한다.

- 조회: `SELECT * FROM push_logs WHERE status = 'DEAD'`
- 재처리: `status → PENDING` 업데이트 후 Celery re-enqueue
- `push_logs`에 이미 `title`, `content`, `idempotency_key`, `error_message`가 있어 별도 페이로드 저장 불필요

---

## 상태 전이

```
PENDING       created_at ←── job 생성
  └─▶ [전송 시작]  send_at ←── 전체 조회 + 청크 처리 + 송신제어
        ├─▶ SENT        completed_at ←── 완료
        └─▶ FAILED      (일시 실패, retry 예약)
              ├─▶ SENT    completed_at ←── 재시도 성공
              └─▶ DEAD    failed_at   ←── max_retries 초과, DLQ 이동
                    └─▶ PENDING  (DLQ 수동 재처리)
```
