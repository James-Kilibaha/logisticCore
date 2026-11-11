from uuid import UUID

from pydantic import BaseModel, Field

ACCOUNT_KINDS = ("CASH", "BANK", "MOBILE")


class CategorySave(BaseModel):
    name: str = Field(..., min_length=1)
    kind: str = "EXPENSE"            # EXPENSE | INCOME
    description: str | None = None


class AccountSave(BaseModel):
    name: str = Field(..., min_length=1)
    kind: str = "BANK"               # CASH | BANK | MOBILE
    accountNo: str | None = None     # Cash: inaweza kuachwa wazi
    currencyType: str = "TZS"
    office_id: UUID | None = None
    openingBalance: float = 0
    openingDate: str | None = None   # YYYY-MM-DD


class IncomeSave(BaseModel):
    details: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    currency: str = "TZS"
    category_id: UUID | None = None
    institute_id: UUID | None = None
    office_id: UUID | None = None


class IncomeSearch(BaseModel):
    startDate: str | None = None
    endDate: str | None = None
    office_id: str | None = None
    category_id: str | None = None
    institute_id: str | None = None


class TransferSave(BaseModel):
    from_id: UUID
    to_id: UUID
    amount: float = Field(..., gt=0)      # kwa sarafu ya akaunti INAYOTOA
    toAmount: float | None = None         # kilichopokelewa (sarafu ya akaunti inayopokea) - kama sarafu tofauti
    note: str | None = None


class EquitySave(BaseModel):
    kind: str = "CAPITAL"                 # CAPITAL (mtaji ulioingizwa) | DRAWING (mmiliki amechukua)
    amount: float = Field(..., gt=0)
    currency: str = "TZS"
    institute_id: UUID | None = None
    owner: str | None = None
    details: str | None = None


class LockSave(BaseModel):
    month: str                            # YYYY-MM
    note: str | None = None
