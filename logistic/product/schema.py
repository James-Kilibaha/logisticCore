from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, model_validator

CARRIER_TYPES = ("AIR", "SEA")
_TRACK = AliasChoices("trackNumber", "qrcodeOrBarcodeTrack")


def _normalise(product: "Create | Update") -> None:
    if product.carrierType is not None:
        product.carrierType = product.carrierType.strip().upper()
        if product.carrierType not in CARRIER_TYPES:
            raise ValueError(f"carrierType must be one of {', '.join(CARRIER_TYPES)}")
    if product.trackNumber is not None:
        product.trackNumber = str(product.trackNumber).strip() or None


class Create(BaseModel):
    description: str = Field(..., min_length=1)
    unitPrice: float = Field(0.0, ge=0)
    quantities: float = Field(0.0, ge=0)
    weight: float = Field(0.0, ge=0)
    trackNumber: str | None = Field(None, validation_alias=_TRACK)
    carrierType: str = "AIR"  # app ya zamani haikutuma carrierType
    length: float | None = 0.0
    width: float | None = 0.0
    height: float | None = 0.0
    priceId: UUID | None = None
    invoiceId: UUID
    officeCode: str | None = None  # code ya ofisi ya mzigo huu; tupu = mfumo unatengeneza

    @model_validator(mode="after")
    def validate_product(self):
        _normalise(self)
        if self.carrierType == "SEA":
            for field in ("length", "width", "height"):
                if not getattr(self, field) or getattr(self, field) <= 0:
                    raise ValueError(f"{field} is required for SEA cargo")
        return self


class Update(BaseModel):
    """Sehemu zisizotumwa (au null) zinabaki kama zilivyo."""
    id: UUID
    description: str | None = None
    unitPrice: float | None = Field(None, ge=0)
    quantities: float | None = Field(None, ge=0)
    weight: float | None = Field(None, ge=0)
    trackNumber: str | None = Field(None, validation_alias=_TRACK)
    carrierType: str | None = None
    length: float | None = None
    width: float | None = None
    height: float | None = None
    priceId: UUID | None = None

    @model_validator(mode="after")
    def validate_product(self):
        _normalise(self)
        return self
