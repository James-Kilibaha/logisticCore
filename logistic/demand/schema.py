from uuid import UUID

from pydantic import BaseModel, Field

from ..shipment.schema import CostCreate


class Fill(BaseModel):
    costs: list[CostCreate] = Field(..., min_length=1)


class Reason(BaseModel):
    reason: str = Field(..., min_length=2)


class RuleSave(BaseModel):
    enabled: bool = True
    categories: list[str] = []          # [] = gharama yoyote
    responsible: str = "DOER"           # DOER | ROLE
    role_id: UUID | None = None
    remindHour: int = 17
    graceDays: int = 0
    blockScope: str = "EVERYONE"        # EVERYONE | RESPONSIBLE | NONE


class FillMany(BaseModel):
    """Kujaza gharama moja kwa mabox mengi (mf. nauli ya mabox 10 yaliyosafirishwa leo)."""
    demandIds: list[UUID] = Field(..., min_length=1)
    category: str
    currency: str = "TZS"
    # EACH = kila box `amount`; EQUAL = `amount` ni jumla inagawanywa sawa; WEIGHT = jumla kwa uzito (kg);
    # MANUAL = `amounts` {demand_id: kiasi}
    mode: str = "EACH"
    amount: float | None = None
    amounts: dict[str, float] = {}
    payStatus: str = "PAID"             # PAID | PARTIAL | CREDIT
    paidAmount: float | None = None     # PARTIAL: kilicholipwa kwa jumla (kinagawanywa kwa uwiano)
    supplier: str | None = None
    institute_id: UUID | None = None
    note: str | None = None
    preview: bool = False               # true = onyesha mgawanyo tu, usihifadhi
