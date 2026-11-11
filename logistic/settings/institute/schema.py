from pydantic import BaseModel, Field


class Create(BaseModel):
    name: str = Field(..., min_length=1)
    accountNo: str = Field(..., min_length=1)
    currencyType: str = Field(..., min_length=1)


class Filter(BaseModel):
    id: str | None = None
    name: str | None = None
    accountNo: str | None = None
    currencyType: str | None = None
    isBlocked: bool | None = None


class Update(Create):
    id: str
