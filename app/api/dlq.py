from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from supabase import AsyncClient

from app.core.database import get_db
from app.core.redis import get_redis
from app.schemas.dlq import DlqItem, DlqListResponse, DlqRetryResponse
from app.tasks.push import send_push_task

router = APIRouter(prefix="/dlq", tags=["dlq"])


@router.get("", response_model=DlqListResponse)
async def list_dlq(
    limit: int = 20,
    offset: int = 0,
    db: AsyncClient = Depends(get_db),
) -> DlqListResponse:
    res = await db.table("push_logs").select("*").eq("status", "DEAD").range(offset, offset + limit - 1).execute()
    total_res = await db.table("push_logs").select("id", count="exact").eq("status", "DEAD").execute()

    items = [DlqItem(**row) for row in res.data]
    total = total_res.count or 0

    return DlqListResponse(items=items, total=total)


@router.post("/{idempotency_key}/retry", status_code=200, response_model=DlqRetryResponse)
async def retry_dlq(
    idempotency_key: str,
    db: AsyncClient = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> DlqRetryResponse:
    res = await db.table("push_logs").select("*").eq("idempotency_key", idempotency_key).eq("status", "DEAD").execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="dead push not found")

    row = res.data[0]
    push_id = row["id"]

    await db.table("push_logs").update({
        "status": "PENDING",
        "retry_count": 0,
        "error_message": None,
        "failed_at": None,
    }).eq("id", push_id).execute()

    # 멱등성 키 삭제 후 재큐잉 (키가 살아있으면 태스크가 중복으로 판단해 즉시 종료됨)
    await redis.delete(f"idempotency:{idempotency_key}")

    send_push_task.delay(push_id, idempotency_key, row["title"], row["content"])

    return DlqRetryResponse(push_id=push_id, status="PENDING")
