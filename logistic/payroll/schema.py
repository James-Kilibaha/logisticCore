from uuid import UUID

from pydantic import BaseModel, Field


class EmployeeSave(BaseModel):
    name: str = Field(..., min_length=1)
    phone: str | None = None
    position: str | None = None
    office_id: UUID | None = None
    basic: float = Field(..., ge=0)
    allowance: float = Field(0, ge=0)
    deduction: float = Field(0, ge=0)
    nssf: bool = True
    paye: bool = True
    tin: str | None = None
    nssfNo: str | None = None
    bank: str | None = None
    active: bool = True


class SettingsSave(BaseModel):
    nssfEmployee: float = 10.0
    nssfEmployer: float = 10.0
    sdl: float = 3.5
    sdlEnabled: bool = False
    wcf: float = 0.5
    payeBands: list[list[float | None]] = []


class Prepare(BaseModel):
    month: str                     # YYYY-MM


class LineEdit(BaseModel):
    basic: float | None = Field(None, ge=0)
    allowance: float = Field(0, ge=0)
    deduction: float = Field(0, ge=0)


class Post(BaseModel):
    institute_id: UUID | None = None   # akaunti iliyolipa mishahara (net)
