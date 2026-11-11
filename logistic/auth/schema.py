from pydantic import BaseModel

from ..user.schema import AuthUser


class Login(BaseModel):
    username: str
    password: str


class Refresh(BaseModel):
    refresh_token: str


class LoginResponse(BaseModel):
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "bearer"
    expires_in: int = 0  # sekunde
    user: AuthUser | None = None
    # Hatua ya pili (2FA): tokeni hazitolewi mpaka code ya SMS ithibitishwe kwa /api/login/otp
    otpRequired: bool = False
    otpToken: str | None = None
    phoneHint: str | None = None
    otpTtlMinutes: int | None = None


class OtpVerify(BaseModel):
    otpToken: str
    code: str


class OtpResend(BaseModel):
    otpToken: str


class Forgot(BaseModel):
    username: str


class ForgotReset(BaseModel):
    resetToken: str
    code: str
    newPassword: str
