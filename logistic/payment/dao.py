from datetime import datetime

from sqlalchemy.orm import joinedload

from ..core.dao import BaseDao, to_uuid
from ..core.enums import EPaymentStatus
from .model import Debt, Payment


class DebtDao(BaseDao[Debt]):
    model = Debt

    def by_invoice(self, invoice_id) -> Debt | None:
        return self.find_one(Debt.invoice_id == to_uuid(invoice_id))

    def by_invoice_with_payments(self, invoice_id) -> Debt | None:
        return self.find_one(Debt.invoice_id == to_uuid(invoice_id),
                             options=[joinedload(Debt.payment).joinedload(Payment.institute)])

    def unpaid(self, debt_id) -> Debt | None:
        return self.find_one(Debt.id == to_uuid(debt_id),
                             Debt.status.in_([EPaymentStatus.OPEN.name, EPaymentStatus.DEBT.name]))

    def for_invoices(self, invoice_ids, before: datetime) -> list[Debt]:
        return self.find_all(Debt.invoice_id.in_(invoice_ids), Debt.created_at < before)


class PaymentDao(BaseDao[Payment]):
    model = Payment
