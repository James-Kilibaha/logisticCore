from uuid import UUID

from pydantic import BaseModel, Field


class Create(BaseModel):
    customer_id: UUID
    office_id: UUID | None = None
    history: str | None = None


class SetOffice(BaseModel):
    id: UUID
    office_id: UUID | None = None


class UpdateStatus(BaseModel):
    id: UUID
    status: str
    history: str | None = None


class Search(BaseModel):
    id: str | None = None
    invoiceNumber: str | None = None
    status: str | None = None
    customer_id: str | None = None
    office_id: str | None = None
    statuses: list[str] | None = None     # hali kadhaa kwa pamoja
    q: str | None = None                  # namba ya ankara, jina/simu ya mteja, track number, mpokeaji
    offset: int = Field(0, ge=0)
    limit: int | None = Field(None, ge=1, le=500)  # None = zote (app ya zamani)


class InvoiceStatusRef(BaseModel):
    """Kutambua invoice kwa id + hali yake (kutengeneza PDF)."""
    id: str | None = None
    status: str | None = None


class CustomerStatus(BaseModel):
    status: str
    customer_id: UUID
    history: str | None = None


class Block(BaseModel):
    id: UUID
    status: str
    history: str | None = None
    customer_id: UUID | None = None
