from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..plan.schema import PlanOut


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    plan_id: UUID
    status: str
    startsAt: datetime
    endsAt: datetime
    note: str | None = None
    createdBy: str | None = None
    created_at: datetime | None = None
    plan: PlanOut | None = None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    plan_id: UUID
    subscription_id: UUID | None = None
    periods: int
    amount: float
    currency: str
    method: str | None = None
    reference: str | None = None
    status: str
    note: str | None = None
    submittedBy: str | None = None
    reviewedBy: str | None = None
    reviewedAt: datetime | None = None
    created_at: datetime | None = None
    plan: PlanOut | None = None
    couponCode: str | None = None
    discount: float | None = None
    startMode: str | None = None


class SubmitPayment(BaseModel):
    """Kampuni inatuma taarifa ya malipo iliyofanya (inasubiri uthibitisho wako)."""
    plan_id: UUID
    periods: int = Field(1, ge=1, le=24)
    amount: float = Field(..., gt=0)
    currency: str = "TZS"
    method: str = Field(..., min_length=2, max_length=40)
    reference: str = Field(..., min_length=3, max_length=80)
    note: str | None = Field(None, max_length=500)
    couponCode: str | None = Field(None, max_length=30)
    startMode: str | None = Field(None, max_length=10)   # QUEUE (chaguo-msingi) | NOW - kwa mpango mdogo tu


class RecordPayment(BaseModel):
    """Wewe (platform admin) unarekodi malipo yaliyopokelewa - subscription inaongezwa papo hapo."""
    company_id: UUID
    plan_id: UUID
    periods: int = Field(1, ge=1, le=36)
    amount: float = Field(..., ge=0)
    currency: str = "TZS"
    method: str | None = None
    reference: str | None = None
    note: str | None = None
    couponCode: str | None = None
    discount: float | None = None
    startMode: str | None = None


class ReviewPayment(BaseModel):
    note: str | None = Field(None, max_length=500)


class Extend(BaseModel):
    """Kuongeza muda bila malipo (zawadi, marekebisho) au kuanzisha majaribio upya."""
    company_id: UUID
    plan_id: UUID | None = None   # None = mpango wa sasa
    days: int = Field(..., ge=1, le=1100)
    status: str = "ACTIVE"        # ACTIVE | TRIAL
    note: str | None = None


class ChangePlan(BaseModel):
    """Kubadilisha mpango wa kipindi cha sasa papo hapo (kupandisha/kushusha)."""
    company_id: UUID
    plan_id: UUID
