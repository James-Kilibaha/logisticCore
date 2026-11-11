"""
Stoo (Tanzania): kupokea box, kuona wateja wenye mizigo stoo na kutengeneza invoice.
Haina table yake - inaunganisha huduma za invoice, customer na package.
"""
from sqlalchemy.orm import Session

from ..customer import service as customer_service
from ..invoice import service as invoice_service
from ..package import service as package_service
from . import schema


def generate_invoice_pdf(db: Session, data: schema.InvoiceStatusRef):
    return invoice_service.generate_pdf(db, data)


def search_invoices(db: Session, data: schema.Search, current_user_id=None):
    return invoice_service.search(db, data, current_user_id)


def customers_by_invoice_status(db: Session, status: str):
    return customer_service.by_invoice_status(db, status)


def customers_by_invoice_account(db: Session, status: str):
    return customer_service.by_invoice_account(db, status)


def change_invoice_status(db: Session, data: schema.UpdateStatus):
    return invoice_service.change_status(db, data)


def receive_package(db: Session, data: schema.MarkCollected, user_id=None):
    return package_service.mark_collected(db, data, user_id)


def packages_by_flags(db: Session, is_collect: bool, is_box_close: bool):
    return package_service.by_flags(db, is_collect, is_box_close)
