"""Query za dashboard (zinasoma tu)."""
from datetime import datetime

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session, joinedload

from ..core.enums import EPaymentStatus
from ..customer.model import Customer
from ..expense.model import Expense
from ..invoice.model import Invoice
from ..package.model import Package
from ..payment.model import Debt, Payment
from ..sms.model import Sms


class DashboardDao:
    """`office` != None: takwimu za ofisi hiyo tu (ankara zisizo na ofisi zinahesabiwa pia)."""

    def __init__(self, db: Session, office=None):
        self.db = db
        self.office = office

    def _inv(self, q):
        if self.office is None:
            return q
        return q.filter(or_(Invoice.office_id == self.office, Invoice.office_id.is_(None)))

    def invoice_counts(self) -> dict[str, int]:
        rows = self._inv(self.db.query(Invoice.status, func.count(Invoice.id))).group_by(Invoice.status).all()
        return {status: count for status, count in rows}

    def customers(self) -> int:
        return self.db.query(func.count(Customer.id)).scalar() or 0

    def boxes(self, is_box_close: bool, is_collect: bool) -> int:
        return (self.db.query(func.count(Package.id))
                .filter(Package.isBoxClose.is_(is_box_close), Package.isCollect.is_(is_collect)).scalar() or 0)

    def outstanding_debt(self) -> float:
        q = self.db.query(func.coalesce(func.sum(Debt.debt), 0.0)).filter(Debt.status != EPaymentStatus.PAID.name)
        if self.office is not None:
            q = self._inv(q.join(Invoice, Invoice.id == Debt.invoice_id))
        return float(q.scalar() or 0)

    def paid_since(self, start: datetime) -> float:
        q = self.db.query(func.coalesce(func.sum(case((Payment.kind == "REFUND", -Payment.paid), else_=Payment.paid)),
                                        0.0)).filter(Payment.created_at >= start)
        if self.office is not None:
            q = self._inv(q.join(Debt, Debt.id == Payment.debt_id).join(Invoice, Invoice.id == Debt.invoice_id))
        return float(q.scalar() or 0)

    def expenses_since(self, start: datetime) -> float:
        from ..expense.dao import approved_filter

        q = self.db.query(func.coalesce(func.sum(Expense.amount), 0.0)).filter(Expense.created_at >= start,
                                                                              approved_filter())
        if self.office is not None:
            q = q.filter(Expense.office_id == self.office)
        return float(q.scalar() or 0)

    def pending_sms(self) -> int:
        return self.db.query(func.count(Sms.id)).filter(Sms.isSMSSend.is_(False)).scalar() or 0

    def payments_since(self, start: datetime) -> list[tuple[datetime, float]]:
        q = self.db.query(Payment.created_at,
                          case((Payment.kind == "REFUND", -Payment.paid), else_=Payment.paid)).filter(Payment.created_at >= start)
        if self.office is not None:
            q = self._inv(q.join(Debt, Debt.id == Payment.debt_id).join(Invoice, Invoice.id == Debt.invoice_id))
        return q.all()

    def recent_invoices(self, limit: int) -> list[Invoice]:
        return (self._inv(self.db.query(Invoice))
                .options(joinedload(Invoice.customer), joinedload(Invoice.product))
                .order_by(Invoice.created_at.desc().nullslast(), Invoice.invoiceNumber.desc())
                .limit(limit).all())
