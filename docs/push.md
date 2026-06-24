# 푸시 (Fake FCM)

## 개요

실제 FCM 대신 **Fake FCM**으로 푸시 전송을 시뮬레이션한다.  
디바이스 토큰이 없는 환경에서 멱등성, 재시도, DLQ 흐름을 검증하는 것이 목적이다.

## Fake FCM 동작

랜덤 성공/실패를 반환하여 실제 FCM의 응답을 시뮬레이션한다.

```python
import random

FAKE_FCM_SUCCESS_RATE = 0.9  # 90% 성공률 (환경변수로 조정 가능)

def fake_fcm_send(token: str, title: str, content: str) -> bool:
    return random.random() < FAKE_FCM_SUCCESS_RATE
```

- 성공 → `success_count` 누적
- 실패 → `failed_count` 누적, 재시도 대상으로 처리

## 전송 흐름

```
users 전체 조회
└── 청크 분할 (예: 100건 단위)
    └── 청크별 송신 제어 (30ms, 동시 전송 수 제한)
        └── Fake FCM 전송 (토큰별 랜덤 성공/실패)
            ├── 성공 → success_count +1
            └── 실패 → failed_count +1

전체 청크 완료
├── SENT 처리 (completed_at 기록)
└── 실패율 임계 초과 시 → retry 스케줄
```

## 오류 처리

| 상황 | 처리 |
|---|---|
| 단건 전송 실패 | `failed_count` 누적, 전체 흐름 계속 진행 |
| 전체 실패율 임계 초과 | Celery retry (지수 백오프) |
| max_retries(3) 초과 | `push_logs.status = 'DEAD'`, DLQ 이동 |

## 재시도 전략 (지수 백오프)

| 시도 | 대기 시간 |
|---|---|
| 1차 재시도 | 60초 |
| 2차 재시도 | 120초 |
| 3차 재시도 | 240초 |
| 초과 | DLQ (`status = 'DEAD'`) |

## 디바이스 토큰

실제 디바이스 토큰 없이 CSV 덤프 데이터로 `users` 테이블에 더미 토큰을 미리 적재한다.

```sql
-- 더미 토큰 예시
INSERT INTO users (device_token) VALUES
  ('dummy-token-00001'),
  ('dummy-token-00002'),
  ...
```

Fake FCM은 토큰 유효성을 검증하지 않고 랜덤 결과만 반환한다.