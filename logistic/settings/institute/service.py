from sqlalchemy.orm import Session

from ...core.exceptions import Conflict, NotFound
from . import schema
from .dao import InstituteDao
from .model import Institute


def create(db: Session, data: schema.Create, current_user_id) -> Institute:
    dao = InstituteDao(db)
    account = data.accountNo.strip()
    if dao.by_account(account):
        raise Conflict("Financial Institute Is Exited...")
    return dao.create(name=data.name.strip(), accountNo=account, currencyType=data.currencyType.strip(),
                      logsId=current_user_id)


def search(db: Session, f: schema.Filter):
    return InstituteDao(db).search(f)


def _get(dao: InstituteDao, institute_id) -> Institute:
    institute = dao.get(institute_id)
    if institute is None or institute.isBlocked:
        raise NotFound("Taasisi haipo")
    return institute


def update(db: Session, data: schema.Update) -> Institute:
    dao = InstituteDao(db)
    institute = _get(dao, data.id)
    account = data.accountNo.strip()
    other = dao.by_account(account)
    if other is not None and other.id != institute.id:
        raise Conflict("Namba hii ya akaunti ipo tayari")
    return dao.update(institute, name=data.name.strip(), accountNo=account,
                      currencyType=data.currencyType.strip().upper())


def delete(db: Session, institute_id) -> dict:
    """Yenye malipo / cash-up inafichwa tu (historia ya malipo inabaki); isiyotumika inafutwa."""
    from ...cashup.model import CashUpLine
    from ...payment.model import Payment

    dao = InstituteDao(db)
    institute = _get(dao, institute_id)
    used = db.query(Payment).filter(Payment.institute_id == institute.id).first() is not None
    if not used:
        used = db.query(CashUpLine).filter(CashUpLine.institute_id == institute.id).first() is not None
    if used:
        dao.update(institute, isBlocked=True)
        return {"deleted": True, "archived": True}
    dao.delete(institute)
    return {"deleted": True, "archived": False}
