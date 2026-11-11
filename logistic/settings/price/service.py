from sqlalchemy.orm import Session

from ...core.exceptions import NotFound
from ..currency.dao import CurrencyDao
from . import schema
from .dao import PriceDao
from .model import Price


def create(db: Session, data: schema.Create, current_user_id) -> Price:
    """Bei mpya; bei ya zamani yenye jina na uzito ule ule inazuiwa."""
    currency = CurrencyDao(db).get(data.currency_id)
    if currency is None:
        raise NotFound("No currency Exited..")

    dao = PriceDao(db)
    for old in dao.active_same(currency.name, data.weight, data.unit):
        dao.update(old, commit=False, isBlocked=True)
    return dao.create(name=currency.name, weight=data.weight, cost=data.cost, unit=data.unit,
                      currency_id=currency.id, logsId=current_user_id)


def search(db: Session, f: schema.Filter):
    return PriceDao(db).search(f)


def delete(db: Session, price_id) -> dict:
    """Bei inazuiwa (si kufutwa): bidhaa za zamani zilizotumia bei hii zinaendelea kuionyesha."""
    dao = PriceDao(db)
    price = dao.get(price_id)
    if price is None or price.isBlocked:
        raise NotFound("Bei hii haipo")
    dao.update(price, isBlocked=True)
    return {"deleted": True}
