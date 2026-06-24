from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PushRequest(BaseModel):
    title: str
    content: str
    idempotency_key: str | None = None


class PushResponse(BaseModel):
    push_id: UUID
    idempotency_key: str
    status: str


class PushStatusResponse(BaseModel):
    id: UUID
    idempotency_key: str
    title: str
    content: str
    success_count: int
    failed_count: int
    status: str
    retry_count: int
    error_message: str | None
    created_at: datetime
    send_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
