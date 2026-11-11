"""Query za ripoti (zinasoma tu; hazibadilishi data)."""
from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from ..core.enums import EPaymentStatus
from ..expense.dao import ExpenseDao
from ..invoice.model import Invoice
from ..payment.model import Debt, Payment
from ..settings.institute.model import Institute


class ReportDao:
    def __init__(self, db: Session):
        self.db = db

    def _invoices(self):
        return (self.db.query(Invoice)
                .options(joinedload(Invoice.customer), joinedload(Invoice.product),
                         joinedload(Invoice.debt).joinedload(Debt.payment))
                .join(Debt, Invoice.id == Debt.invoice_id))

    def invoices_by_debt_status_between(self, status: str, start: datetime, end: datetime) -> list[Invoice]:
        return (self._invoices()
                .filter(Debt.created_at >= start, Debt.created_at < end, Debt.status == status)
                .order_by(Debt.created_at).all())

    def invoices_with_debt(self, status: str | None) -> list[Invoice]:
        statuses = {EPaymentStatus.OPEN.name, EPaymentStatus.DEBT.name}
        if status:
            statuses.add(status)
        return self._invoices().filter(or_(*[Debt.status == s for s in statuses])).order_by(Debt.created_at).all()

    def invoices_between(self, start: datetime, end: datetime) -> list[Invoice]:
        return self._invoices().filter(Debt.created_at >= start, Debt.created_at < end).order_by(Debt.created_at).all()

    def income_by_institute(self, start: datetime, end: datetime):
        return (self.db.query(Payment.institute_id, Institute.name.label("name"),
                              Institute.currencyType.label("currencyType"),
                              func.sum(Payment.paid).label("total"))
                .join(Institute, Payment.institute_id == Institute.id)
                .filter(Payment.created_at >= start, Payment.created_at < end)
                .group_by(Payment.institute_id, Institute.name, Institute.currencyType)
                .order_by(Institute.name).all())

    def expenses_between(self, start: datetime, end: datetime, office_id=None):
        return ExpenseDao(self.db).between(start, end, office_id)
