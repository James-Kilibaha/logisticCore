from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class Item(BaseModel):
    description: str = Field(..., min_length=1)
    carrierType: str = "AIR"
    quantities: float = Field(1, ge=0)
    weight: float = Field(0, ge=0)                  # kg (ndege) / kg za mzigo (meli -> tani)
    cbm: float | None = Field(None, ge=0)           # meli: CBM yote (au vipimo vya katoni hapa chini)
    length: float | None = Field(None, ge=0)
    width: float | None = Field(None, ge=0)
    height: float | None = Field(None, ge=0)
    priceId: UUID | None = None                     # tupu = bei ya sasa ya usafiri huo
    amount: float | None = Field(None, ge=0)        # hiari: kiasi cha mkono (badala ya kuhesabu)

    @field_validator("carrierType")
    @classmethod
    def _carrier(cls, v: str) -> str:
        v = (v or "AIR").strip().upper()
        if v not in ("AIR", "SEA"):
            raise ValueError("carrierType must be AIR or SEA")
        return v


class Save(BaseModel):
    customerId: UUID | None = None
    customerName: str | None = None
    phoneNumber: str | None = None
    validDays: int = Field(14, ge=1, le=365)
    note: str | None = None
    items: list[Item] = Field(default_factory=list)


class Calculate(BaseModel):
    items: list[Item] = Field(default_factory=list)


class Search(BaseModel):
    q: str | None = None
    status: str | None = None
    customerId: UUID | None = None
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)


class SetStatus(BaseModel):
    status: str


class SendSms(BaseModel):
    channel: str = "SMS"
    text: str | None = None


class Convert(BaseModel):
    officeId: UUID | None = None


def valid_until(days: int) -> date:
    from datetime import timedelta

    from ..core.base_model import utc_now

    return (utc_now() + timedelta(days=days)).date()
