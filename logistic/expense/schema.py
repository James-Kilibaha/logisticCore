from uuid import UUID

from pydantic import BaseModel, Field


class Create(BaseModel):
    details: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)          # kwa sarafu `currency`
    office_id: UUID
    currency: str = "TZS"
    category_id: UUID | None = None
    institute_id: UUID | None = None          # akaunti iliyolipa (Cash / Benki / Simu)
    package_id: UUID | None = None            # gharama ya safari (box) hii
    # malipo: PAID = yote; PARTIAL = paidAmount imelipwa, salio deni; CREDIT = yote deni (mf. pango bado halijalipwa)
    payStatus: str = "PAID"
    paidAmount: float | None = None           # kwa sarafu `currency`
    supplier: str | None = None               # tunayemdai - lazima kwa PARTIAL/CREDIT


class Update(Create):
    id: UUID


class Search(BaseModel):
    id: str | None = None
    details: str | None = None
    office_id: str | None = None
    created_at: str | None = None  # 'YYYY-MM-DD' - matumizi ya siku hiyo
    startDate: str | None = None   # au kipindi: startDate..endDate (siku zote mbili zinahesabiwa)
    endDate: str | None = None
    status: str | None = None      # PENDING | APPROVED | REJECTED
    category_id: str | None = None
    institute_id: str | None = None
    package_id: str | None = None


class Reject(BaseModel):
    reason: str = Field(..., min_length=1)


class Pay(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = "TZS"
    institute_id: UUID | None = None
    note: str | None = None
