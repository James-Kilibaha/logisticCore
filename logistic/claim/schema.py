from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .model import CLAIM_STATUSES, CLAIM_TYPES, SETTLEMENTS


class Create(BaseModel):
    invoiceId: UUID
    productId: UUID | None = None
    type: str
    cartons: float | None = Field(None, gt=0)
    description: str = Field(..., min_length=3)

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in CLAIM_TYPES:
            raise ValueError(f"type must be one of {', '.join(CLAIM_TYPES)}")
        return v


class Resolve(BaseModel):
    status: str                      # APPROVED / REJECTED
    compensation: float = Field(0, ge=0)
    settlement: str = "NONE"         # NONE / DISCOUNT / REFUND
    instituteId: UUID | None = None  # inahitajika kwa REFUND
    resolution: str = Field(..., min_length=3)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in ("APPROVED", "REJECTED"):
            raise ValueError("status must be APPROVED or REJECTED")
        return v

    @field_validator("settlement")
    @classmethod
    def _settlement(cls, v: str) -> str:
        v = (v or "NONE").strip().upper()
        if v not in SETTLEMENTS:
            raise ValueError(f"settlement must be one of {', '.join(SETTLEMENTS)}")
        return v


class Display(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    product_id: UUID | None = None
    type: str
    cartons: float | None = None
    description: str
    status: str
    compensation: float
    settlement: str
    resolution: str | None = None
    resolvedAt: datetime | None = None
    created_at: datetime | None = None
    hasPhoto: bool = False
    invoiceNumber: str | None = None
    customerName: str | None = None
    productName: str | None = None
    reportedBy: str | None = None
    resolvedByName: str | None = None


class Filter(BaseModel):
    status: str | None = None
    invoiceId: UUID | None = None
    offset: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=500)


ALL_STATUSES = CLAIM_STATUSES
