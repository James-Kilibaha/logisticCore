from sqlalchemy import JSON, Column, DateTime, Float, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from ..core.base_model import PlatformEntity


class OnlinePayment(PlatformEntity):
    """
    Ombi moja la malipo kwa simu (push USSD). `purpose`:
      - SUBSCRIPTION: kampuni inalipia subscription (akaunti yako ya AzamPay)
      - INVOICE: mteja wa kampuni analipia ankara (akaunti ya AzamPay ya kampuni)
    Iko kwenye table ya mfumo (si ya kampuni) kwa sababu callback ya AzamPay inafika bila kampuni.
    """
    __tablename__ = "online_payments"

    purpose = Column(String, nullable=False)              # SUBSCRIPTION | INVOICE
    company_id = Column(UUID(as_uuid=True), nullable=False)
    externalId = Column(String, nullable=False)           # yetu (utilityref ya AzamPay)
    gateway = Column(String, nullable=False, default="AZAMPAY")
    provider = Column(String, nullable=False)             # Mpesa, Tigo, Airtel, Halopesa, Azampesa
    msisdn = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="TZS")
    status = Column(String, nullable=False, default="PENDING")  # PENDING | SUCCESS | FAILED | EXPIRED
    gatewayRef = Column(String, nullable=True)            # transactionId ya AzamPay
    operatorRef = Column(String, nullable=True)           # kumbukumbu ya mtandao (mf. ya M-Pesa)
    message = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)                 # callback ya mwisho
    completedAt = Column(DateTime, nullable=True)
    # SUBSCRIPTION
    plan_id = Column(UUID(as_uuid=True), nullable=True)
    periods = Column(Integer, nullable=True)
    couponCode = Column(String, nullable=True)
    startMode = Column(String, nullable=True)             # QUEUE | NOW (tazama subscription.service.add_period)
    discount = Column(Float, nullable=True)
    # INVOICE
    debt_id = Column(UUID(as_uuid=True), nullable=True)
    invoice_id = Column(UUID(as_uuid=True), nullable=True)
    invoiceNumber = Column(String, nullable=True)
    # aliyeanzisha na kilichotokana na malipo (SubscriptionPayment / Payment)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    username = Column(String, nullable=True)
    applied_id = Column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (Index("ux_online_payments_external", "externalId", unique=True),
                      Index("ix_online_payments_company", "company_id", "created_at"))
