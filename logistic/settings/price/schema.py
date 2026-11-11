from uuid import UUID

from pydantic import BaseModel, Field, field_validator

PRICE_UNITS = ("KG", "CBM")


class Create(BaseModel):
    name: str | None = None  # inachukuliwa kutoka kwenye sarafu
    weight: float = Field(0.0, ge=0)
    cost: float = Field(0.0, ge=0)
    unit: str = "KG"  # KG au CBM
    currency_id: UUID

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        v = (v or "KG").strip().upper()
        if v not in PRICE_UNITS:
            raise ValueError("unit must be KG or CBM")
        return v


class Filter(BaseModel):
    id: str | None = None
    name: str | None = None
    isBlocked: bool | None = None
    unit: str | None = None
