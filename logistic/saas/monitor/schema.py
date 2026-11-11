from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Impersonate(BaseModel):
    """Kuingia kwenye app ya kampuni kama mtumiaji wake - KUANGALIA TU. user_id=None = msimamizi wake mkuu."""
    user_id: UUID | None = None
    minutes: int = 60


class PageView(BaseModel):
    """App inaripoti ukurasa ambao mtumiaji amefungua (mf. "invoices", "customers/abc")."""
    page: str = Field(..., min_length=1, max_length=120)
    title: str | None = Field(None, max_length=120)


class ActivityRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime | None = None
    company_id: UUID | None = None
    companyName: str | None = None
    companySlug: str | None = None
    username: str | None = None
    module: str
    action: str
    method: str
    path: str
    entity_id: str | None = None
    status_code: int
    ip: str | None = None
    client: str | None = None   # APP / WEB / API
    device: str | None = None   # mf. "Samsung SM-A515F · Android 13"
    summary: str | None = None
