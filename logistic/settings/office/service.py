
from sqlalchemy.orm import Session

from ...core.exceptions import BadRequest, Conflict, NotFound
from ...core import phone as phones
from . import schema
from .dao import OfficeDao
from .model import Office


def _get(dao: OfficeDao, office_id) -> Office:
    office = dao.get(office_id)
    if office is None or office.isBlocked:
        raise NotFound("Ofisi haipo")
    return office


def create(db: Session, data: schema.Create, current_user_id) -> Office:
    from ...saas.subscription.service import check_limit

    dao = OfficeDao(db)
    name, location = data.name.strip(), data.location.strip()
    if dao.by_name_location(name, location):
        raise Conflict("This Office already exists")
    check_limit(db, "offices")  # mipaka ya mpango wa subscription
    return dao.create(name=name, location=location, phoneNumber=phones.normalize(data.phoneNumber),
                      logsId=current_user_id)


def search(db: Session, f: schema.Filter):
    return OfficeDao(db).search(f)


def update(db: Session, data: schema.Update) -> Office:
    dao = OfficeDao(db)
    office = _get(dao, data.id)
    name, location = data.name.strip(), data.location.strip()
    other = dao.by_name_location(name, location)
    if other is not None and other.id != office.id and not other.isBlocked:
        raise Conflict("Ofisi yenye jina na eneo hili ipo tayari")
    return dao.update(office, name=name, location=location, phoneNumber=phones.normalize(data.phoneNumber))


def delete(db: Session, office_id) -> dict:
    """
    Ofisi yenye watumiaji hai haifutwi (wahamishe kwanza). Yenye historia (ankara, matumizi, cash-up, nukuu)
    inafichwa tu (isBlocked) ili ripoti za zamani zibaki; isiyotumika kabisa inafutwa.
    """
    from ...cashup.model import CashUp
    from ...expense.model import Expense
    from ...invoice.model import Invoice
    from ...quotation.model import Quotation
    from ...user.model import User

    dao = OfficeDao(db)
    office = _get(dao, office_id)
    if dao.query().filter(Office.isBlocked.is_(False), Office.id != office.id).count() == 0:
        raise BadRequest("Lazima ibaki angalau ofisi moja")
    users = db.query(User).filter(User.office_id == office.id, User.isBlocked.is_(False)).count()
    if users:
        raise Conflict(f"Ofisi {office.name} ina watumiaji {users}. Wahamishe ofisi nyingine kwanza.")
    used = any(db.query(m).filter(m.office_id == office.id).first() is not None
               for m in (Invoice, Expense, CashUp, Quotation, User))
    if used:
        dao.update(office, isBlocked=True)
        return {"deleted": True, "archived": True}
    dao.delete(office)
    return {"deleted": True, "archived": False}
