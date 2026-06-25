import threading
import uuid

import redis as sync_redis

from app.core.config import settings


def test_idempotency_key_blocks_second_attempt() -> None:
    """같은 키로 SET NX 두 번 시도 → 두 번째는 None 반환"""
    key = str(uuid.uuid4())
    r = sync_redis.from_url(settings.redis_idempotency_url, decode_responses=True)
    try:
        first = r.set(f"idempotency:{key}", "1", ex=86400, nx=True)
        second = r.set(f"idempotency:{key}", "1", ex=86400, nx=True)
        assert first is not None
        assert second is None
    finally:
        r.delete(f"idempotency:{key}")


def test_concurrent_idempotency_key_acquired_once() -> None:
    """동일 키로 N개 스레드가 동시에 SET NX 시도 → 정확히 1개만 성공"""
    N = 10
    key = str(uuid.uuid4())
    r = sync_redis.from_url(settings.redis_idempotency_url, decode_responses=True)

    results: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(N)

    def try_acquire() -> None:
        barrier.wait()  # 모든 스레드 동시 출발
        acquired = r.set(f"idempotency:{key}", "1", ex=86400, nx=True)
        with lock:
            results.append(acquired is not None)

    threads = [threading.Thread(target=try_acquire) for _ in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    try:
        assert sum(results) == 1, f"기대: 1개 획득, 실제: {sum(results)}개 획득"
        assert results.count(False) == N - 1
    finally:
        r.delete(f"idempotency:{key}")
