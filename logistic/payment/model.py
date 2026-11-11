from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import AuditedEntity


class Debt(AuditedEntity):
    """
    Deni la invoice (yote kwa TSh):
        jumla   = amount (usafirishaji) + storageCharge (stoo) - discount (punguzo)
        paid    = malipo yote - pesa zilizorudishwa (refund)
        debt    = jumla - paid  (kilichobaki)
    """
    __tablename__ = "debts"

    amount = Column(Float, nullable=False)
    debt = Column(Float, nullable=False, default=0.0)
    paid = Column(Float, nullable=False, default=0.0)
    status = Column(String, nullable=False)  # EPaymentStatus
    days = Column(Integer, nullable=False, default=0)  # siku mzigo umekaa stoo
    storageCharge = Column(Float, nullable=False, default=0.0, server_default="0")
    discount = Column(Float, nullable=False, default=0.0, server_default="0")
    discountNote = Column(String, nullable=True)
    storageFrom = Column(DateTime, nullable=True)  # mzigo ulipofika stoo (UTC)
    lastReminderAt = Column(DateTime, nullable=True)   # SMS ya mwisho ya kukumbusha deni
    storageWarnedAt = Column(DateTime, nullable=True)  # SMS ya "siku za bure zinakaribia kuisha"
    storageRemindedAt = Column(DateTime, nullable=True)  # kumbusho la mwisho la "mzigo umekaa stoo muda mrefu"

    __table_args__ = (Index("ix_debts_invoice", "invoice_id"), Index("ix_debts_status", "status"))

    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"))

    invoice = relationship("Invoice", back_populates="debt", uselist=True)
    payment = relationship("Payment", back_populates="debt", uselist=True)


class Payment(AuditedEntity):
    """
    Malipo moja (sehemu au yote) ya deni, au pesa iliyorudishwa (kind=REFUND).
    `paid` daima ni TSh; kama mteja alilipa kwa sarafu nyingine, `amountOriginal` + `currency` + `rate`
    zinaonyesha alicholeta.
    """
    __tablename__ = "payments"

    paid = Column(Float, nullable=False, default=0.0)
    kind = Column(String, nullable=False, default="PAYMENT", server_default="PAYMENT")
    currency = Column(String, nullable=False, default="TZS", server_default="TZS")
    amountOriginal = Column(Float, nullable=True)
    rate = Column(Float, nullable=True)
    note = Column(String, nullable=True)
    receiptNumber = Column(String, nullable=True)

    __table_args__ = (Index("ix_payments_receipt", "receiptNumber"), Index("ix_payments_debt", "debt_id"),
                      Index("ix_payments_created", "created_at"))

    debt_id = Column(UUID(as_uuid=True), ForeignKey("debts.id", ondelete="CASCADE"))
    institute_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="CASCADE"))

    debt = relationship("Debt", back_populates="payment", uselist=True)
    institute = relationship("Institute", back_populates="payment", uselist=True)
