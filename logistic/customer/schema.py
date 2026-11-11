from uuid import UUID

from pydantic import BaseModel, Field


class Insert(BaseModel):
    name: str = Field(..., min_length=1)
    phoneNumber: str | None = None  # si lazima; +255XXXXXXXXX
    active: int = 1


class Update(BaseModel):
    id: UUID
    name: str = Field(..., min_length=1)
    phoneNumber: str | None = None


class Block(BaseModel):
    id: UUID | None = None
    phoneNumber: str | None = None


class Search(BaseModel):
    q: str | None = None          # jina au simu
    active: int | None = None     # 1 = hai, 0 = amezuiwa
    offset: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=500)


class CreditLimit(BaseModel):
    id: UUID
    creditLimit: float | None = Field(None, ge=0)  # null = kikomo cha kawaida
