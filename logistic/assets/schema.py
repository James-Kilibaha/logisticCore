from uuid import UUID

from pydantic import BaseModel, Field


class AssetSave(BaseModel):
    name: str = Field(..., min_length=1)
    category: str = "OTHER"
    cost: float = Field(..., gt=0)            # kwa sarafu `currency`
    currency: str = "TZS"
    purchaseDate: str                         # YYYY-MM-DD
    lifeMonths: int = Field(60, ge=1, le=600)
    salvage: float = Field(0, ge=0)           # TSh
    institute_id: UUID | None = None          # akaunti iliyolipa (pesa inatoka)
    office_id: UUID | None = None
    serial: str | None = None
    note: str | None = None


class Dispose(BaseModel):
    date: str                                 # YYYY-MM-DD
    amount: float = Field(0, ge=0)            # TSh iliyopatikana (0 = imeharibika/imetupwa)
    institute_id: UUID | None = None
