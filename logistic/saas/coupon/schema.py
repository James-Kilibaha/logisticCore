from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CouponIn(BaseModel):
    id: UUID | None = None
    code: str = Field(..., min_length=3, max_length=30)
    description: str | None = Field(None, max_length=200)
    kind: str = "PERCENT"
    value: float = Field(..., gt=0)
    planIds: list[UUID] | None = None
    company_id: UUID | None = None
    maxUses: int | None = Field(None, ge=1)
    maxPerCompany: int = Field(1, ge=1, le=100)
    validFrom: datetime | None = None
    validUntil: datetime | None = None
    active: bool = True


class CouponOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    description: str | None = None
    kind: str
    value: float
    planIds: list[str] | None = None
    company_id: UUID | None = None
    maxUses: int | None = None
    maxPerCompany: int
    used: int
    validFrom: datetime | None = None
    validUntil: datetime | None = None
    active: bool
    created_at: datetime | None = None


class CouponCheck(BaseModel):
    code: str = Field(..., min_length=1, max_length=30)
    plan_id: UUID
    periods: int = Field(1, ge=1, le=36)
