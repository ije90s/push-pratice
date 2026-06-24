from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DlqItem(BaseModel):
    id: UUID
    idempotency_key: str
    title: str
    content: str
    retry_count: int
    error_message: str | None
    failed_at: datetime | None
    created_at: datetime


class DlqListResponse(BaseModel):
    items: list[DlqItem]
    total: int


class DlqRetryResponse(BaseModel):
    push_id: UUID
    status: str
