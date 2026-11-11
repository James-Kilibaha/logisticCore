from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ID_TYPES = ("NIDA", "LESENI", "MPIGA_KURA", "PASIPOTI", "NYINGINE")


class Item(BaseModel):
    productId: UUID
    cartons: float = Field(..., gt=0)


class Create(BaseModel):
    invoiceId: UUID
    items: list[Item] | None = None   # None = mzigo wote uliobaki
    collectorName: str = Field(..., min_length=2)
    collectorPhone: str | None = None  # si lazima; +255XXXXXXXXX
    idType: str | None = None
    idNumber: str | None = None
    isReceiver: bool = True
    onCredit: bool = False
    note: str | None = None
    # Code za ofisi za mizigo inayochukuliwa (kutoka SMS / lebo); koma au nafasi kati yake
    officeCode: str | None = None
    officeCodes: list[str] | None = None

    @field_validator("idType")
    @classmethod
    def _id_type(cls, v):
        if v is None or v == "":
            return None
        v = v.strip().upper()
        if v not in ID_TYPES:
            raise ValueError(f"idType must be one of {', '.join(ID_TYPES)}")
        return v


class Display(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    collectorName: str
    collectorPhone: str | None = None
    idType: str | None = None
    idNumber: str | None = None
    isReceiver: bool
    onCredit: bool
    balance: float
    hasSignature: bool = False
    hasPhoto: bool = False
    note: str | None = None
    codeVerified: bool = False
    staffName: str | None = None
    created_at: datetime | None = None
    items: list[dict] = []        # [{productId, description, cartons}]
    partial: bool = False


class Remaining(BaseModel):
    productId: UUID
    description: str
    trackNumber: str | None = None
    cartons: float
    collected: float
    remaining: float
    needsCode: bool = False   # mzigo huu una code ya ofisi


class Status(BaseModel):
    handovers: list[Display]
    remaining: list[Remaining]
    complete: bool
    needsCode: bool = False   # mzigo uliobaki una code: mchukuaji lazima aionyeshe
