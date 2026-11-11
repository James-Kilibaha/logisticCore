from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PlanCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=40)
    name: str = Field(..., min_length=2, max_length=80)
    description: str | None = None
    price: float = Field(0, ge=0)
    currency: str = "TZS"
    months: int = Field(1, ge=1, le=36)
    maxUsers: int | None = Field(None, ge=1)
    maxOffices: int | None = Field(None, ge=1)
    maxInvoicesPerMonth: int | None = Field(None, ge=1)
    modules: list[str] | None = None   # None = moduli zote
    isPublic: bool = True
    isActive: bool = True
    sortOrder: int = 0


class PlanUpdate(PlanCreate):
    id: UUID


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None = None
    price: float
    currency: str
    months: int
    maxUsers: int | None = None
    maxOffices: int | None = None
    maxInvoicesPerMonth: int | None = None
    modules: list[str] | None = None
    isPublic: bool
    isActive: bool
    sortOrder: int
    created_at: datetime | None = None
