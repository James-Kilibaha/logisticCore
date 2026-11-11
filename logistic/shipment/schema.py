from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .model import COST_CATEGORIES


PAY_STATUSES = ("PAID", "PARTIAL", "CREDIT")


class CostCreate(BaseModel):
    category: str
    amount: float = Field(..., gt=0)
    currency: str = "TZS"
    note: str | None = None
    # malipo: PAID = imelipwa yote; PARTIAL = paidAmount imelipwa, salio ni deni; CREDIT = yote ni deni
    payStatus: str = "PAID"
    paidAmount: float | None = None     # kwa sarafu ya gharama (PARTIAL)
    supplier: str | None = None         # tunayemdai/tunayemlipa - lazima kwa PARTIAL/CREDIT
    institute_id: UUID | None = None    # akaunti iliyolipa (sehemu iliyolipwa)

    @field_validator("payStatus")
    @classmethod
    def _pay(cls, v: str) -> str:
        v = (v or "PAID").strip().upper()
        if v not in PAY_STATUSES:
            raise ValueError(f"payStatus must be one of {', '.join(PAY_STATUSES)}")
        return v

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in COST_CATEGORIES:
            raise ValueError(f"category must be one of {', '.join(COST_CATEGORIES)}")
        return v


class Cost(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    category: str
    amount: float
    currency: str
    rate: float
    amountTzs: float
    note: str | None = None
    payStatus: str | None = None
    paidTzs: float | None = None
    owedTzs: float = 0
    supplier: str | None = None
    created_at: datetime | None = None


class CostPay(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = "TZS"
    institute_id: UUID | None = None
    note: str | None = None


class Profit(BaseModel):
    packageId: UUID
    boxId: str
    packageType: str
    trackNumber: str | None = None
    closedAt: datetime | None = None
    items: int
    invoices: int
    kg: float
    cbm: float
    revenue: float         # usafirishaji wa mizigo iliyo ndani (TSh)
    storageCharges: float  # gharama za stoo zilizotozwa kwa ankara za box hili
    costs: float
    profit: float
    margin: float          # % ya mapato
    costPerKg: float
    byCategory: dict[str, float] = {}


class ProfitReport(BaseModel):
    rows: list[Profit]
    revenue: float
    costs: float
    profit: float
    margin: float
    byCarrier: dict[str, dict[str, float]]
