import random
import time
from datetime import datetime, timezone

from supabase import create_client

from app.core.config import settings
from app.services.fake_fcm import fake_fcm_send
from app.worker import celery_app

CHUNK_SIZE = 100
SEND_INTERVAL_SEC = 0.03  # 30ms
TASK_FAILURE_RATE = 0.2   # 태스크 처리 랜덤 실패율 20%


def _get_supabase():
    return create_client(settings.supabase_url, settings.supabase_key)


def _get_redis():
    import redis as sync_redis
    return sync_redis.from_url(settings.redis_idempotency_url, decode_responses=True)


@celery_app.task(
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def send_push_task(self, push_id: str, idempotency_key: str, title: str, content: str) -> None:
    db = _get_supabase()
    redis = _get_redis()

    # 멱등성 확인
    acquired = redis.set(f"idempotency:{idempotency_key}", "1", ex=86400, nx=True)
    if acquired is None:
        return  # 중복 요청, 종료

    # 처리 시작 기록
    db.table("push_logs").update({
        "send_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", push_id).execute()

    # 태스크 처리 랜덤 실패 시뮬레이션
    if random.random() < TASK_FAILURE_RATE:
        error_msg = f"태스크 처리 실패 (retry {self.request.retries + 1})"

        if self.request.retries >= self.max_retries:
            db.table("push_logs").update({
                "status": "DEAD",
                "retry_count": self.request.retries,
                "error_message": error_msg,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", push_id).execute()
            return

        db.table("push_logs").update({
            "retry_count": self.request.retries + 1,
            "error_message": error_msg,
        }).eq("id", push_id).execute()
        raise self.retry(exc=Exception(error_msg), countdown=2 ** self.request.retries * 60)

    # 전체 유저 조회
    res = db.table("users").select("id, device_token").execute()
    users = res.data

    success_count = 0
    failed_count = 0
    total = len(users)

    # 청크 단위 전송 (FCM 실패는 카운트만, retry 없음)
    for i in range(0, total, CHUNK_SIZE):
        chunk = users[i:i + CHUNK_SIZE]
        for user in chunk:
            if fake_fcm_send(user["device_token"], title, content):
                success_count += 1
            else:
                failed_count += 1

        if i + CHUNK_SIZE < total:
            time.sleep(SEND_INTERVAL_SEC)

    # 전송 완료 (FCM 결과와 무관하게 SENT)
    db.table("push_logs").update({
        "status": "SENT",
        "success_count": success_count,
        "failed_count": failed_count,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", push_id).execute()
