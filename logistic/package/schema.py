from datetime import date
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field

_TRACK = AliasChoices("trackNumber", "qrcodeOrBarcodeTrack")


class Insert(BaseModel):
    packageType: str = "GENERAL"
    weight: float = 0.0
    trackNumber: str = Field("", validation_alias=_TRACK)


class AddProduct(BaseModel):
    packageId: UUID
    productId: UUID
    invoiceId: UUID
    productWeight: float = Field(0.0, ge=0)


class RemoveProduct(BaseModel):
    packageId: UUID
    productId: UUID


class ClosePackage(BaseModel):
    id: UUID
    productWeight: float = Field(..., ge=0)
    # tupu = mfumo unatengeneza track number ya safari (mf. ACME-A261110-001)
    trackNumber: str = Field("", validation_alias=_TRACK)
    status: str = "SHIPPING"
    history: str | None = None  # ikiachwa, server inaiandika
    isBoxClose: bool = True
    eta: date | None = None  # ikiachwa: leo + ETA_AIR_DAYS / ETA_SEA_DAYS


class SetEta(BaseModel):
    eta: date
    notify: bool = False  # kuwajulisha wateja wa box hili kwa SMS
    reason: str | None = None


class MarkCollected(BaseModel):
    id: UUID
    status: str = "STORE"
    history: str | None = None
    isCollect: bool = True
    # False (kawaida): mzigo unapokelewa bila SMS; zinatumwa baadaye kwa mmoja mmoja au wote (notify-store)
    sendSms: bool = False


class NotifyStore(BaseModel):
    """SMS za "mzigo umefika" kwa ankara zilizochaguliwa ndani ya box (tupu = zote)."""
    invoiceIds: list[UUID] | None = None
    toReceiver: bool = True
