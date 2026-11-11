from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from ..core.dao import BaseDao
from ..invoice.model import Invoice
from ..receiver.model import Receiver
from .model import Customer


class CustomerDao(BaseDao[Customer]):
    model = Customer

    def by_phone(self, phone: str | None) -> Customer | None:
        return self.find_one(Customer.phoneNumber == phone) if phone else None

    def all_ordered(self) -> list[Customer]:
        return self.find_all(order_by=Customer.name)

    def search(self, f) -> list[Customer]:
        q = self.query()
        if f.q and f.q.strip():
            text = f.q.strip()
            from ..core.phone import search_digits

            digits = search_digits(text)
            conds = [Customer.name.ilike(f"%{text}%")]
            if len(digits) >= 3:
                conds.append(Customer.phoneNumber.ilike(f"%{digits}%"))
            q = q.filter(or_(*conds))
        if f.active is not None:
            q = q.filter(Customer.active == f.active)
        return q.order_by(Customer.name).offset(f.offset).limit(f.limit).all()

    def counts(self) -> dict:
        rows = dict(self.db.query(Customer.active, func.count(Customer.id)).group_by(Customer.active).all())
        return {"all": sum(rows.values()), "active": rows.get(1, 0), "blocked": sum(v for k, v in rows.items() if k != 1)}

    def not_blocked(self) -> list[Customer]:
        return self.find_all(Customer.active == 1, options=[joinedload(Customer.invoice)], order_by=Customer.name)

    def by_invoice_status(self, status: str) -> list[Customer]:
        return (self.query(joinedload(Customer.invoice).joinedload(Invoice.receiver))
                .outerjoin(Invoice, Invoice.customer_id == Customer.id)
                .outerjoin(Receiver, Receiver.invoice_id == Invoice.id)
                .filter(Invoice.status == status)
                .order_by(Customer.name).all())

    def by_invoice_account(self, status: str) -> list[Customer]:
        return (self.query(joinedload(Customer.invoice).options(joinedload(Invoice.receiver),
                                                                joinedload(Invoice.debt)))
                .outerjoin(Invoice, Invoice.customer_id == Customer.id)
                .outerjoin(Receiver, Receiver.invoice_id == Invoice.id)
                .filter(Invoice.status == status)
                .order_by(Customer.name).all())
