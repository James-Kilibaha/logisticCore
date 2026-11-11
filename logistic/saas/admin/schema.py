from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Login(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    fullName: str
    phone: str | None = None
    email: str | None = None
    active: bool
    lastLoginAt: datetime | None = None
    created_at: datetime | None = None
    totpEnabled: bool = False
    role: str = "OWNER"


class LoginResponse(BaseModel):
    access_token: str = ""
    token_type: str = "bearer"
    expires_in: int = 0
    admin: AdminOut | None = None
    # Hatua ya pili: akaunti yenye 2FA inapata `challenge` - tokeni inatolewa baada ya code (/login/2fa)
    twoFactorRequired: bool = False
    challenge: str | None = None


class TwoFactorLogin(BaseModel):
    challenge: str = Field(..., min_length=10)
    code: str = Field(..., min_length=6, max_length=12)  # tarakimu 6 za app, au code ya dharura XXXX-XXXX


class TwoFactorCode(BaseModel):
    code: str = Field(..., min_length=6, max_length=12)


class TwoFactorConfirm(BaseModel):
    password: str = Field(..., min_length=1)
    code: str = Field(..., min_length=6, max_length=12)


class AdminCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=60)
    password: str = Field(..., min_length=8)
    fullName: str = Field(..., min_length=2)
    phone: str | None = None
    email: str | None = None
    role: str = "OWNER"


class AdminUpdate(BaseModel):
    id: UUID
    fullName: str = Field(..., min_length=2)
    phone: str | None = None
    email: str | None = None
    active: bool = True
    password: str | None = Field(None, min_length=8)   # nywila mpya (si lazima)
    role: str | None = None                            # None = haibadiliki


class ChangePassword(BaseModel):
    oldPassword: str
    newPassword: str = Field(..., min_length=8)


class ResetTenantPassword(BaseModel):
    """Kumsaidia msimamizi wa kampuni aliyesahau nywila (atalazimika kuweka mpya akiingia)."""
    username: str = Field(..., min_length=1)
    newPassword: str = Field(..., min_length=8)


class Forgot(BaseModel):
    username: str = Field(..., min_length=1, max_length=120)  # jina, simu au email


class ForgotReset(BaseModel):
    resetToken: str = Field(..., min_length=10)
    code: str = Field(..., min_length=4, max_length=10)
    newPassword: str = Field(..., min_length=1)
