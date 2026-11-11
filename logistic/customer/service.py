from sqlalchemy.orm import Session

from ..core.exceptions import Conflict, NotFound
from ..core import phone as phones
from ..core.utils import title
from . import schema
from .dao import CustomerDao
from .model import Customer


def _get_or_404(dao: CustomerDao, customer_id) -> Customer:
    customer = dao.get(customer_id)
    if customer is None:
        raise NotFound("The Customer does not exist")
    return customer


def create(db: Session, data: schema.Insert, current_user_id) -> Customer:
    dao = CustomerDao(db)
    phone = phones.normalize(data.phoneNumber)
    if phone and dao.by_phone(phone):
        raise Conflict("Customer Existed...")
    return dao.create(name=title(data.name), phoneNumber=phone, active=data.active, logsId=current_user_id)


def update(db: Session, data: schema.Update) -> Customer:
    dao = CustomerDao(db)
    customer = _get_or_404(dao, data.id)
    phone = phones.normalize(data.phoneNumber)
    other = dao.by_phone(phone) if phone else None
    if other and other.id != customer.id:
        raise Conflict("Another Customer already uses this phone number")
    return dao.update(customer, name=title(data.name), phoneNumber=phone)


def toggle_block(db: Session, data: schema.Block) -> Customer:
    dao = CustomerDao(db)
    customer = dao.get(data.id) if data.id else dao.by_phone(phones.try_normalize(data.phoneNumber))
    if customer is None:
        raise NotFound("The Customer does not exist")
    return dao.update(customer, active=0 if customer.active == 1 else 1)


def delete(db: Session, customer_id) -> bool:
    dao = CustomerDao(db)
    return dao.delete(_get_or_404(dao, customer_id))


def list_all(db: Session):
    return CustomerDao(db).all_ordered()


def list_not_blocked(db: Session):
    return CustomerDao(db).not_blocked()


def by_invoice_status(db: Session, status: str):
    return CustomerDao(db).by_invoice_status(status)


def by_invoice_account(db: Session, status: str):
    return CustomerDao(db).by_invoice_account(status)


def search(db: Session, f: schema.Search):
    return CustomerDao(db).search(f)


def counts(db: Session) -> dict:
    return CustomerDao(db).counts()


def set_credit_limit(db: Session, data: schema.CreditLimit) -> Customer:
    from ..core.audit import note
    from ..core.utils import whole

    dao = CustomerDao(db)
    customer = _get_or_404(dao, data.id)
    customer = dao.update(customer, creditLimit=data.creditLimit)
    note(f"Kikomo cha mkopo cha {customer.name}: "
         + ("cha kawaida" if data.creditLimit is None else f"TSh {whole(data.creditLimit)}"))
    return customer


def credit_status(db: Session, customer_id) -> dict:
    from ..core.dao import to_uuid
    from ..payment import credit

    customer = CustomerDao(db).get(to_uuid(customer_id)) if to_uuid(customer_id) else None
    if customer is None:
        raise NotFound("The Customer does not exist")
    return credit.status(db, customer)
