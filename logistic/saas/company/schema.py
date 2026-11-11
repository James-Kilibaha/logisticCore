from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_COLOR = r"^#[0-9A-Fa-f]{6}$"


class CompanyAdmin(BaseModel):
    """Msimamizi wa kwanza wa kampuni (anapata ruhusa zote ndani ya kampuni yake)."""
    firstName: str = Field(..., min_length=1)
    lastName: str = Field(..., min_length=1)
    username: str = Field(..., min_length=3, max_length=60)
    password: str = Field(..., min_length=8)
    phoneNumber: str | None = None


class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    slug: str = Field(..., min_length=3, max_length=30)
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    country: str | None = "Tanzania"
    tin: str | None = None
    domain: str | None = None
    primaryColor: str | None = Field(None, pattern=_COLOR)
    accentColor: str | None = Field(None, pattern=_COLOR)
    ownerName: str | None = None
    ownerPhone: str | None = None
    notes: str | None = None
    plan_id: UUID | None = None      # None = mpango wa bei ya chini kabisa
    trialDays: int | None = Field(None, ge=0, le=365)   # 0 = bila majaribio (subscription inaanza ukilipia)
    admin: CompanyAdmin


class Signup(BaseModel):
    """Kampuni inajisajili yenyewe (ukurasa wa "Fungua akaunti")."""
    companyName: str = Field(..., min_length=2, max_length=120)
    slug: str = Field(..., min_length=3, max_length=30)
    phone: str = Field(..., min_length=9)
    email: str | None = None
    country: str | None = "Tanzania"
    plan_id: UUID | None = None
    admin: CompanyAdmin


class CompanyUpdate(BaseModel):
    """Platform admin: kubadilisha taarifa zote za kampuni."""
    id: UUID
    name: str = Field(..., min_length=2, max_length=120)
    slug: str = Field(..., min_length=3, max_length=30)
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    country: str | None = None
    tin: str | None = None
    domain: str | None = None
    primaryColor: str | None = Field(None, pattern=_COLOR)
    accentColor: str | None = Field(None, pattern=_COLOR)
    ownerName: str | None = None
    ownerPhone: str | None = None
    notes: str | None = None
    legalName: str | None = None


class ProfileUpdate(BaseModel):
    """Kampuni yenyewe: jina, mawasiliano na rangi (slug na domain zinabadilishwa na wewe tu)."""
    name: str = Field(..., min_length=2, max_length=120)
    legalName: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    country: str | None = None
    tin: str | None = None
    primaryColor: str | None = Field(None, pattern=_COLOR)
    accentColor: str | None = Field(None, pattern=_COLOR)


class SettingsUpdate(BaseModel):
    """Mipangilio ya biashara: {"DAYS_TO_CHARGE": 7, "SMS_SOURCE_NAME": "YMG", ...}. null/"" = tumia ya kawaida."""
    values: dict[str, Any]


class StatusUpdate(BaseModel):
    id: UUID
    status: str   # ACTIVE | SUSPENDED
    reason: str | None = None


class Approve(BaseModel):
    """Kuthibitisha kampuni iliyojisajili: mpango na siku za majaribio (None = ulioombwa / TRIAL_DAYS)."""
    plan_id: UUID | None = None
    trialDays: int | None = Field(None, ge=0, le=365)
    note: str | None = Field(None, max_length=500)


class Reject(BaseModel):
    reason: str | None = Field(None, max_length=500)


class LimitsUpdate(BaseModel):
    """Nafasi za ziada juu ya mpango (mf. extraUsers=2: Starter yenye watumiaji 3 inapata 5). 0 = kama mpango."""
    extraUsers: int = Field(0, ge=0, le=10000)
    extraOffices: int = Field(0, ge=0, le=10000)
    extraInvoicesPerMonth: int = Field(0, ge=0, le=10_000_000)


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    legalName: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    country: str | None = None
    tin: str | None = None
    logoPath: str | None = None
    primaryColor: str | None = None
    accentColor: str | None = None
    domain: str | None = None
    status: str
    ownerName: str | None = None
    ownerPhone: str | None = None
    source: str | None = None
    created_at: datetime | None = None


class CompanyAdminOut(CompanyOut):
    notes: str | None = None
    signupPlanId: str | None = None
    approvedBy: str | None = None
    approvedAt: datetime | None = None
    extraUsers: int = 0
    extraOffices: int = 0
    extraInvoicesPerMonth: int = 0
