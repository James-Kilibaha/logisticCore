from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Search(BaseModel):
    userId: UUID | None = None
    module: str | None = None
    action: str | None = None
    failed: bool | None = None
    client: str | None = None  # APP / WEB / API
    q: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    offset: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=500)


class Row(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime | None = None
    user_id: UUID | None = None
    username: str | None = None
    module: str
    action: str
    method: str
    path: str
    entity_id: str | None = None
    status_code: int
    ip: str | None = None
    summary: str | None = None
    detail: str | None = None
    client: str | None = None
    device: str | None = None


class Page(BaseModel):
    total: int
    items: list[Row]
