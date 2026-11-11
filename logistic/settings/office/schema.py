from uuid import UUID

from pydantic import BaseModel, Field


class Create(BaseModel):
    name: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    phoneNumber: str | None = None


class Filter(BaseModel):
    id: str | None = None
    name: str | None = None
    location: str | None = None
    phoneNumber: str | None = None
    isBlocked: bool | None = None


class Update(Create):
    id: UUID
