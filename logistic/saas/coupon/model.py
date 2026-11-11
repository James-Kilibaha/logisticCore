from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from ...core.base_model import PlatformEntity


class Coupon(PlatformEntity):
    """Punguzo la subscription: asilimia (PERCENT) au kiasi (AMOUNT, TZS) kwa kila malipo."""
    __tablename__ = "coupons"

    code = Column(String, nullable=False)                 # herufi kubwa, mf. KARIBU20
    description = Column(String, nullable=True)
    kind = Column(String, nullable=False, default="PERCENT")   # PERCENT | AMOUNT
    value = Column(Float, nullable=False)
    planIds = Column(JSON, nullable=True)                 # None = mipango yote
    company_id = Column(UUID(as_uuid=True), nullable=True)  # None = kampuni zote
    maxUses = Column(Integer, nullable=True)              # None = bila kikomo
    maxPerCompany = Column(Integer, nullable=False, default=1, server_default="1")
    used = Column(Integer, nullable=False, default=0, server_default="0")
    validFrom = Column(DateTime, nullable=True)
    validUntil = Column(DateTime, nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    createdBy = Column(String, nullable=True)

    __table_args__ = (Index("ux_coupons_code", "code", unique=True),)


class CouponUse(PlatformEntity):
    __tablename__ = "coupon_uses"

    coupon_id = Column(UUID(as_uuid=True), nullable=False)
    company_id = Column(UUID(as_uuid=True), nullable=False)
    payment_id = Column(UUID(as_uuid=True), nullable=True)   # SubscriptionPayment
    discount = Column(Float, nullable=False, default=0)

    __table_args__ = (Index("ix_coupon_uses_coupon", "coupon_id", "company_id"),)
