from sqlalchemy import Column, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from ..core.base_model import AuditedEntity

COST_CATEGORIES = ("FREIGHT", "CUSTOMS", "CLEARING", "TRANSPORT", "HANDLING", "OTHER")


class PackageCost(AuditedEntity):
    """
    Gharama ya kusafirisha box/kontena moja: nauli (ndege/meli), ushuru, clearing, usafiri wa ndani ...
    `amountTzs` = amount x rate (TSh) - inahifadhiwa ili ripoti zisibadilike kiwango kikibadilika.
    """
    __tablename__ = "package_costs"

    package_id = Column(UUID(as_uuid=True), ForeignKey("packages.id", ondelete="CASCADE"), nullable=False)
    category = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="TZS")
    rate = Column(Float, nullable=False, default=1.0)
    amountTzs = Column(Float, nullable=False)
    note = Column(String, nullable=True)
    # v2.17 malipo ya gharama: PAID (imelipwa yote) | PARTIAL (nusu, salio ni deni) | CREDIT (yote kwa deni).
    # Za zamani: payStatus/paidTzs = None -> zinahesabiwa kuwa zimelipwa.
    payStatus = Column(String, nullable=True)
    paidTzs = Column(Float, nullable=True)
    supplier = Column(String, nullable=True)     # tunayemlipa / tunayemdai: wakala, msafirishaji ...

    __table_args__ = (Index("ix_package_costs_package", "package_id"),
                      Index("ix_package_costs_pay", "payStatus"))

    @property
    def owedTzs(self) -> float:
        """Deni lililobaki kwa gharama hii (TSh)."""
        if self.paidTzs is None:
            return 0.0
        return round(max((self.amountTzs or 0) - (self.paidTzs or 0), 0.0), 2)


class CostPayment(AuditedEntity):
    """Malipo ya gharama ya box (ya mwanzo au ya kulipa deni baadaye) - yanatoka kwenye akaunti ya fedha."""
    __tablename__ = "package_cost_payments"

    cost_id = Column(UUID(as_uuid=True), ForeignKey("package_costs.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)                    # TSh
    currency = Column(String, nullable=False, default="TZS", server_default="TZS")
    amountOriginal = Column(Float, nullable=True)
    rate = Column(Float, nullable=True)
    institute_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="SET NULL"), nullable=True)
    note = Column(String, nullable=True)

    __table_args__ = (Index("ix_package_cost_payments_cost", "cost_id"),
                      Index("ix_package_cost_payments_created", "created_at"))
