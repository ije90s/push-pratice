# API 명세

- Base URL: `http://localhost:8000`
- Flower 모니터링 URL: `http://localhost:5500`

---

## 푸시

### 푸시 전송 요청

전체 유저 대상 massive push job을 생성한다.

```
POST /push
```

**요청 본문**

```json
{
  "title": "새로운 메시지",
  "content": "공지사항입니다."
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `title` | string | ✅ | 알림 제목 |
| `content` | string | ✅ | 알림 본문 |

**응답 `201 Created`**

```json
{
  "push_id": "push-uuid-001",
  "idempotency_key": "req-abc-001",
  "status": "PENDING"
}
```

**오류**

| 상태 코드 | 사유 |
|---|---|
| `400` | 필수 필드 누락 또는 유효하지 않은 값 |

---

### 푸시 상태 조회

```
GET /push/{push_id}
```

**응답 `200 OK`**

```json
{
  "push_id": "push-uuid-001",
  "title": "새로운 메시지",
  "content": "공지사항입니다.",
  "status": "SENT",
  "success_count": 198432,
  "failed_count": 1568,
  "retry_count": 0,
  "created_at": "2026-06-24T10:00:00Z",
  "send_at": "2026-06-24T10:00:01Z",
  "completed_at": "2026-06-24T10:02:15Z",
  "failed_at": null
}
```

| `status` 값 | 설명 |
|---|---|
| `PENDING` | 큐에 등록됨, 처리 대기 중 |
| `SENT` | 전송 완료 |
| `FAILED` | 재시도 중 (일시적 실패) |
| `DEAD` | DLQ로 이동됨 (최대 재시도 초과) |

---

## DLQ (관리용)

### DLQ 목록 조회

```
GET /dlq?limit=20&offset=0
```

`push_logs` 테이블에서 `status = 'DEAD'`인 레코드를 조회한다.

**응답 `200 OK`**

```json
{
  "total": 5,
  "items": [
    {
      "push_id": "push-uuid-001",
      "idempotency_key": "req-abc-001",
      "title": "새로운 메시지",
      "content": "공지사항입니다.",
      "error_message": "UNAVAILABLE",
      "retry_count": 3,
      "created_at": "2026-06-24T10:00:00Z",
      "failed_at": "2026-06-24T10:05:00Z"
    }
  ]
}
```

### DLQ 메시지 재처리

```
POST /dlq/{idempotency_key}/retry
```

**응답 `200 OK`**

```json
{
  "push_id": "push-uuid-001",
  "status": "PENDING"
}
```
