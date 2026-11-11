from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    firstName: str = Field(..., min_length=1)
    lastName: str = Field(..., min_length=1)
    phoneNumber: str | None = None  # si lazima; +255XXXXXXXXX
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=4)
    office_id: UUID | None = None
    allOffices: bool = True
    role_id: UUID | None = None


class UserUpdate(BaseModel):
    id: UUID
    firstName: str = Field(..., min_length=1)
    lastName: str = Field(..., min_length=1)
    phoneNumber: str | None = None  # si lazima; +255XXXXXXXXX
    office_id: UUID | None = None
    allOffices: bool | None = None


class UserChangePass(BaseModel):
    id: UUID
    password: str = Field(..., min_length=4)


class UserBlock(BaseModel):
    id: UUID
    active: int | None = None


class DisplayUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    firstName: str
    lastName: str
    phoneNumber: str | None = None
    active: int
    username: str
    office_id: UUID | None = None
    allOffices: bool = True
    role_id: UUID | None = None
    mustChangePassword: bool = False
    twoFactor: bool = False


class AuthUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    firstName: str
    lastName: str
    phoneNumber: str | None = None
    office_id: UUID | None = None
    allOffices: bool = True
    role_id: UUID | None = None
    mustChangePassword: bool = False
    twoFactor: bool = False
    username: str
    active: int
    isBlocked: bool
    created_at: datetime | None = None


class OfficeBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    location: str
    phoneNumber: str | None = None


class UserWithOffice(DisplayUser):
    """Haitoi password - tofauti na zamani ambapo hash ya password ilirudishwa."""
    isBlocked: bool = False
    created_at: datetime | None = None
    office: list[OfficeBrief] = []


class ChangeOwnPassword(BaseModel):
    oldPassword: str
    newPassword: str


class TwoFactor(BaseModel):
    id: UUID
    enabled: bool
