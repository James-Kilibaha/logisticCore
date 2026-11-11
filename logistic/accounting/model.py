"""
Uhasibu rahisi.

- Akaunti za fedha = taasisi (`institutes`): Cash ya ofisi, Benki, Simu. Malipo ya ankara tayari yanaingia humo.
- `AccountCategory`: makundi ya matumizi (EXPENSE) na ya mapato mengine (INCOME).
- `Income`: mapato yasiyotoka kwenye ankara (pango, huduma nyingine ...).
- `Transfer`: kuhamisha pesa kati ya akaunti (mf. Cash -> Benki).
Kiasi chote kinahifadhiwa kwa TSh (`amount`); kama ni sarafu nyingine `amountOriginal` + `currency` + `rate`.
"""
from sqlalchemy import Column, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from ..core.base_model import AuditedEntity

KINDS = ("EXPENSE", "INCOME")


class AccountCategory(AuditedEntity):
    __tablename__ = "account_categories"

    name = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="EXPENSE")   # EXPENSE | INCOME
    description = Column(String, nullable=True)

    __table_args__ = (Index("ix_account_categories_kind", "kind"),)


class Income(AuditedEntity):
    __tablename__ = "account_incomes"

    details = Column(String, nullable=False)
    amount = Column(Float, nullable=False)                 # TSh
    currency = Column(String, nullable=False, default="TZS", server_default="TZS")
    amountOriginal = Column(Float, nullable=True)
    rate = Column(Float, nullable=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("account_categories.id", ondelete="SET NULL"), nullable=True)
    institute_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="SET NULL"), nullable=True)
    office_id = Column(UUID(as_uuid=True), ForeignKey("offices.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (Index("ix_account_incomes_created", "created_at"),)


class Transfer(AuditedEntity):
    __tablename__ = "account_transfers"

    from_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="CASCADE"), nullable=False)
    to_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)                 # TSh
    note = Column(String, nullable=True)
    # v2.18: kiasi kwa sarafu ya kila akaunti (akaunti za USD n.k.)
    fromAmount = Column(Float, nullable=True)              # kilichotoka (sarafu ya akaunti inayotoa)
    toAmount = Column(Float, nullable=True)                # kilichoingia (sarafu ya akaunti inayopokea)

    __table_args__ = (Index("ix_account_transfers_created", "created_at"),)


EQUITY_KINDS = ("CAPITAL", "DRAWING")


class Equity(AuditedEntity):
    """Mtaji ulioingizwa na mmiliki (CAPITAL) au pesa alizochukua mmiliki (DRAWING) - si mapato wala matumizi."""
    __tablename__ = "account_equity"

    kind = Column(String, nullable=False)                  # CAPITAL | DRAWING
    owner = Column(String, nullable=True)
    details = Column(String, nullable=True)
    amount = Column(Float, nullable=False)                 # TSh
    currency = Column(String, nullable=False, default="TZS", server_default="TZS")
    amountOriginal = Column(Float, nullable=True)
    rate = Column(Float, nullable=True)
    institute_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (Index("ix_account_equity_created", "created_at"),)


class PeriodLock(AuditedEntity):
    """Mwezi uliofungwa: rekodi za mwezi huo haziwezi kuongezwa, kubadilishwa wala kufutwa."""
    __tablename__ = "account_period_locks"

    month = Column(String, nullable=False)    # YYYY-MM (moja kwa kila kampuni)
    note = Column(String, nullable=True)

    __table_args__ = (Index("ux_account_period_locks_month", "company_id", "month", unique=True),)
