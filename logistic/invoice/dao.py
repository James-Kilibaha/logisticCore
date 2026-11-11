from sqlalchemy import exists, or_
from sqlalchemy.orm import joinedload, selectinload

from ..core.dao import BaseDao, to_uuid
from ..customer.model import Customer
from ..product.model import Product
from ..receiver.model import Receiver
from ..settings.price.model import Price
from .model import Invoice


class InvoiceDao(BaseDao[Invoice]):
    model = Invoice

    def last_number(self) -> str | None:
        row = self.db.query(Invoice.invoiceNumber).order_by(Invoice.invoiceNumber.desc()).first()
        return row[0] if row else None

    def all_ordered(self) -> list[Invoice]:
        return self.find_all(order_by=Invoice.invoiceNumber.desc())

    def by_status(self, status: str) -> list[Invoice]:
        return self.find_all(Invoice.status == status, order_by=Invoice.invoiceNumber.desc())

    def by_customer(self, customer_id) -> list[Invoice]:
        return self.find_all(Invoice.customer_id == to_uuid(customer_id), order_by=Invoice.invoiceNumber.desc())

    def by_customer_and_status(self, customer_id, status: str, with_products: bool = False) -> list[Invoice]:
        options = [joinedload(Invoice.product)] if with_products else []
        return self.find_all(Invoice.customer_id == to_uuid(customer_id), Invoice.status == status,
                             options=options, order_by=Invoice.invoiceNumber.desc())

    def with_customer_and_products(self, invoice_id, status: str | None = None) -> Invoice | None:
        criteria = [Invoice.id == to_uuid(invoice_id)]
        if status is not None:
            criteria.append(Invoice.status == status)
        return self.find_one(*criteria, options=[joinedload(Invoice.customer), joinedload(Invoice.product)])

    def with_details(self, invoice_id) -> Invoice | None:
        """Invoice + mteja + mpokeaji + bidhaa na bei zake (kwa SMS)."""
        return self.find_one(Invoice.id == to_uuid(invoice_id),
                             options=[joinedload(Invoice.customer), joinedload(Invoice.receiver),
                                      joinedload(Invoice.product).joinedload(Product.price)])

    def with_details_by_status(self, status: str) -> list[Invoice]:
        return self.find_all(Invoice.status == status,
                             options=[joinedload(Invoice.customer), joinedload(Invoice.receiver),
                                      joinedload(Invoice.product)],
                             order_by=Invoice.invoiceNumber)

    def search(self, f, scope_office=None) -> list[Invoice]:
        """
        Kutafuta ankara. `scope_office` = ofisi ambayo mtumiaji amefungiwa (ankara zisizo na ofisi zinaonekana pia).
        `f.q` inatafuta namba ya ankara, mteja (jina/simu), mpokeaji (jina/simu/pickup code) na mizigo
        (track number/maelezo). `f.limit`/`f.offset` = kurasa.
        """
        q = self.db.query(Invoice)
        if f.id is not None:
            q = q.filter(Invoice.id == to_uuid(f.id))
        if f.invoiceNumber is not None:
            q = q.filter(Invoice.invoiceNumber == f.invoiceNumber)
        if f.status is not None:
            q = q.filter(Invoice.status == f.status)
        if getattr(f, "statuses", None):
            q = q.filter(Invoice.status.in_(f.statuses))
        if f.customer_id is not None:
            q = q.filter(Invoice.customer_id == to_uuid(f.customer_id))
        if getattr(f, "office_id", None):
            q = q.filter(Invoice.office_id == to_uuid(f.office_id))
        if scope_office is not None:
            q = q.filter(or_(Invoice.office_id == scope_office, Invoice.office_id.is_(None)))
        text = (getattr(f, "q", None) or "").strip()
        if text:
            from ..core.phone import search_digits

            like = f"%{text}%"
            digits = search_digits(text)
            plike = f"%{digits}%" if len(digits) >= 6 else like  # 0712.. inapata +255712..
            q = q.filter(or_(
                Invoice.invoiceNumber.ilike(like),
                exists().where(Customer.id == Invoice.customer_id,
                               or_(Customer.name.ilike(like), Customer.phoneNumber.ilike(plike))),
                exists().where(Receiver.invoice_id == Invoice.id,
                               or_(Receiver.name.ilike(like), Receiver.phoneNumber.ilike(plike),
                                   Receiver.trackNumber.ilike(like))),
                exists().where(Product.invoice_id == Invoice.id,
                               or_(Product.trackNumber.ilike(like), Product.description.ilike(like),
                                   Product.officeCode.ilike(like))),
            ))
        q = q.options(
            selectinload(Invoice.product).joinedload(Product.price).joinedload(Price.currency),
            selectinload(Invoice.receiver),
            selectinload(Invoice.debt),
            selectinload(Invoice.customer),
            selectinload(Invoice.handover),
        ).order_by(Invoice.invoiceNumber.desc())
        if getattr(f, "offset", 0):
            q = q.offset(f.offset)
        if getattr(f, "limit", None):
            q = q.limit(f.limit)
        return q.all()

    def change_status(self, invoice: Invoice, status: str, history: str | None, commit: bool = True) -> Invoice:
        invoice.status = status
        if history:
            invoice.history = f"{invoice.history},{history}" if invoice.history else history
        return self.update(invoice, commit=commit)
