from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import AuditedEntity


class Expense(AuditedEntity):
    """Matumizi ya ofisi."""
    __tablename__ = "expenses"

    details = Column(String, nullable=False)
    amount = Column(Float, nullable=False)

    office_id = Column(UUID(as_uuid=True), ForeignKey("offices.id", ondelete="CASCADE"))
    office = relationship("Office", back_populates="expense", uselist=True)

    # v2.15 uhasibu. `amount` daima ni TSh; sarafu nyingine -> amountOriginal + currency + rate
    currency = Column(String, nullable=False, default="TZS", server_default="TZS")
    amountOriginal = Column(Float, nullable=True)
    rate = Column(Float, nullable=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("account_categories.id", ondelete="SET NULL"), nullable=True)
    institute_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="SET NULL"), nullable=True)
    package_id = Column(UUID(as_uuid=True), ForeignKey("packages.id", ondelete="SET NULL"), nullable=True)
    # PENDING (inasubiri idhini ya mhasibu) | APPROVED | REJECTED. Za zamani zote ni APPROVED.
    status = Column(String, nullable=False, default="APPROVED", server_default="APPROVED")
    approvedBy = Column(UUID(as_uuid=True), nullable=True)
    approvedAt = Column(DateTime, nullable=True)
    rejectReason = Column(String, nullable=True)
    receipt = Column(String, nullable=True)   # picha ya risiti (njia ya faili)
    # v2.18 malipo: PAID | PARTIAL (salio ni deni) | CREDIT (yote ni deni). None = ya zamani (imelipwa yote).
    payStatus = Column(String, nullable=True)
    paidTzs = Column(Float, nullable=True)
    supplier = Column(String, nullable=True)

    __table_args__ = (Index("ix_expenses_created", "created_at"), Index("ix_expenses_office", "office_id"),
                      Index("ix_expenses_status", "status"), Index("ix_expenses_package", "package_id"))

    @property
    def owedTzs(self) -> float:
        if self.paidTzs is None:
            return 0.0
        return round(max((self.amount or 0) - (self.paidTzs or 0), 0.0), 2)


class ExpensePayment(AuditedEntity):
    """Malipo ya matumizi (ya mwanzo au ya kulipa deni baadaye) - yanatoka kwenye akaunti ya fedha."""
    __tablename__ = "expense_payments"

    expense_id = Column(UUID(as_uuid=True), ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)                    # TSh
    currency = Column(String, nullable=False, default="TZS", server_default="TZS")
    amountOriginal = Column(Float, nullable=True)
    rate = Column(Float, nullable=True)
    institute_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="SET NULL"), nullable=True)
    initial = Column(Boolean, nullable=False, default=False, server_default="false")
    note = Column(String, nullable=True)

    __table_args__ = (Index("ix_expense_payments_expense", "expense_id"),)
