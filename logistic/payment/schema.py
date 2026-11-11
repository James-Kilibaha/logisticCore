from uuid import UUID

from pydantic import BaseModel, Field


class CreatePayment(BaseModel):
    paid: float = Field(..., gt=0)          # kiasi kwa sarafu `currency`
    debtId: UUID
    instituteId: UUID
    currency: str = "TZS"                   # TZS, USD, ...
    note: str | None = None


class SearchPayment(BaseModel):
    invoiceId: UUID


class Discount(BaseModel):
    debtId: UUID
    amount: float = Field(..., ge=0)        # TSh; 0 = kuondoa punguzo
    note: str = Field(..., min_length=2)


class Refund(BaseModel):
    debtId: UUID
    instituteId: UUID
    amount: float = Field(..., gt=0)        # TSh
    note: str = Field(..., min_length=2)
