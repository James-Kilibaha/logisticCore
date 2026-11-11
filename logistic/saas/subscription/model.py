from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ...core.base_model import PlatformEntity


class Subscription(PlatformEntity):
    """
    Kipindi kimoja cha subscription ya kampuni (TRIAL au ACTIVE). Kila malipo yanaongeza kipindi kipya
    kinachoanza pale cha sasa kinapoishia. Subscription ya sasa = kipindi chenye `endsAt` ya mbali zaidi.
    """
    __tablename__ = "subscriptions"

    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String, nullable=False, default="ACTIVE")   # TRIAL | ACTIVE | CANCELLED
    startsAt = Column(DateTime, nullable=False)
    endsAt = Column(DateTime, nullable=False)
    note = Column(String, nullable=True)
    createdBy = Column(String, nullable=True)

    plan = relationship("Plan", lazy="joined")

    __table_args__ = (Index("ix_subscriptions_company", "company_id", "endsAt"),)


class SubscriptionPayment(PlatformEntity):
    """
    Malipo ya kampuni kwako. Kampuni inatuma taarifa ya malipo (PENDING) - wewe unathibitisha (CONFIRMED)
    na subscription inaongezwa yenyewe; au unarekodi malipo moja kwa moja kwenye admin panel.
    """
    __tablename__ = "subscription_payments"

    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True)
    periods = Column(Integer, nullable=False, default=1)      # mara ngapi za muda wa mpango (plan.months)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="TZS")
    method = Column(String, nullable=True)                    # M-PESA, BANK, CASH ...
    reference = Column(String, nullable=True)                 # namba ya muamala
    status = Column(String, nullable=False, default="PENDING")  # PENDING | CONFIRMED | REJECTED
    note = Column(Text, nullable=True)
    submittedBy = Column(String, nullable=True)
    reviewedBy = Column(String, nullable=True)
    reviewedAt = Column(DateTime, nullable=True)
    couponCode = Column(String, nullable=True)                # punguzo lililotumika (tazama saas/coupon)
    # mpango mdogo kuliko uliolipiwa: QUEUE = unaanza siku za sasa zikiisha; NOW = siku zilizobaki zinafutwa
    startMode = Column(String, nullable=True)
    discount = Column(Float, nullable=True)

    plan = relationship("Plan", lazy="joined")

    __table_args__ = (Index("ix_subscription_payments_company", "company_id", "created_at"),
                      Index("ix_subscription_payments_status", "status"))
