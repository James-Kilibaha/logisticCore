from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field


class Insert(BaseModel):
    name: str = Field(..., min_length=1)
    phoneNumber: str | None = None  # si lazima; +255XXXXXXXXX
    trackNumber: str = Field(..., min_length=1,
                             validation_alias=AliasChoices("trackNumber", "qrcodeOrBarcodeTrack"))
    active: int = 1
    status: str = "PARKING"
    history: str | None = None  # ikiachwa, server inaiandika
    isCargoOkay: bool | None = None
    customer_id: UUID | None = None
    invoice_id: UUID


class Update(BaseModel):
    id: UUID
    name: str = Field(..., min_length=1)
    phoneNumber: str | None = None
    trackNumber: str = Field(..., min_length=1,
                             validation_alias=AliasChoices("trackNumber", "qrcodeOrBarcodeTrack"))


class Block(BaseModel):
    id: UUID | None = None
    phoneNumber: str | None = None
