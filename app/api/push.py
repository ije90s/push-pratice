import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from supabase import AsyncClient

from app.core.database import get_db
from app.schemas.push import PushRequest, PushResponse, PushStatusResponse
from app.tasks.push import send_push_task

router = APIRouter(prefix="/push", tags=["push"])


@router.post("", status_code=201, response_model=PushResponse)
async def create_push(
    body: PushRequest,
    db: AsyncClient = Depends(get_db),
) -> PushResponse:
    push_id = str(uuid.uuid4())
    idempotency_key = str(uuid.uuid4())

    await db.table("push_logs").insert({
        "id": push_id,
        "idempotency_key": idempotency_key,
        "title": body.title,
        "content": body.content,
    }).execute()

    send_push_task.delay(push_id, idempotency_key, body.title, body.content)

    return PushResponse(push_id=push_id, idempotency_key=idempotency_key, status="PENDING")


@router.get("/{push_id}", response_model=PushStatusResponse)
async def get_push_status(
    push_id: str,
    db: AsyncClient = Depends(get_db),
) -> PushStatusResponse:
    res = await db.table("push_logs").select("*").eq("id", push_id).execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="push not found")

    return PushStatusResponse(**res.data[0])