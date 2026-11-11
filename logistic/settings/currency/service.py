from sqlalchemy.orm import Session

from ...core.exceptions import Conflict, NotFound
from . import schema
from ..price.dao import PriceDao
from .dao import CurrencyDao
from .model import Currency


def create(db: Session, data: schema.Create, current_user_id) -> Currency:
    """Kiwango kipya cha sarafu; vya zamani vya jina hilo vinazuiwa (historia inabaki)."""
    dao = CurrencyDao(db)
    name = data.name.strip()
    active = dao.active_by_name(name)
    if any(c.buy == data.buy for c in active):
        raise Conflict("This rate already exists")
    for old in active:
        dao.update(old, commit=False, isBlocked=True)
    currency = dao.create(commit=False, name=name, buy=data.buy, logsId=current_user_id)
    db.flush()
    # Bei zinazotumika za sarafu hii zinaanza kutumia kiwango kipya mara moja.
    PriceDao(db).repoint_active(name, currency.id)
    dao.commit(currency)
    return currency


def search(db: Session, f: schema.Filter):
    return CurrencyDao(db).search(f)


def _get(dao: CurrencyDao, currency_id) -> Currency:
    currency = dao.get(currency_id)
    if currency is None or currency.isBlocked:
        raise NotFound("Kiwango hiki hakipo (huenda kimeshabadilishwa)")
    return currency


def update(db: Session, data: schema.Update) -> Currency:
    """Kurekebisha kiwango cha sasa mahali pale pale; bei zinazokitumia zinafuata mara moja."""
    dao = CurrencyDao(db)
    currency = _get(dao, data.id)
    return dao.update(currency, buy=data.buy)


def delete(db: Session, currency_id) -> dict:
    """
    Kuondoa sarafu (mf. KES) isiyotumika tena. Viwango vyake vyote vinazuiwa (historia na ankara za zamani
    zinabaki). Kama kuna bei hai zinazotumia sarafu hii, zifute kwanza.
    """
    from ..price.model import Price

    dao = CurrencyDao(db)
    currency = _get(dao, currency_id)
    prices = db.query(Price).filter(Price.name == currency.name, Price.isBlocked.is_(False)).count()
    if prices:
        raise Conflict(f"Kuna bei {prices} zinazotumia {currency.name}. Zifute kwanza kwenye Bei za usafirishaji.")
    for c in dao.active_by_name(currency.name):
        dao.update(c, commit=False, isBlocked=True)
    db.commit()
    return {"deleted": True, "name": currency.name}


def delete_rate(db: Session, currency_id) -> dict:
    """
    Kufuta kiwango cha sasa kilichokosewa: kiwango cha awali cha sarafu hiyo kinarudi kutumika na bei zote hai
    zinarudishwa kwake. Kama hakuna kiwango cha awali, ni sawa na kuondoa sarafu (delete).
    """
    from ..price.model import Price

    dao = CurrencyDao(db)
    current = _get(dao, currency_id)
    previous = (db.query(Currency).filter(Currency.name == current.name, Currency.id != current.id)
                .order_by(Currency.created_at.desc()).first())
    if previous is None:
        out = delete(db, currency_id)
        return {**out, "restored": None}

    dao.update(previous, commit=False, isBlocked=False)
    db.flush()
    PriceDao(db).repoint_active(current.name, previous.id)
    db.flush()
    still_used = db.query(Price.id).filter(Price.currency_id == current.id).first() is not None
    if still_used:   # bei za zamani (zilizozuiwa) zinakielekea: kibaki kwenye historia kikiwa kimezuiwa
        dao.update(current, commit=False, isBlocked=True)
    else:
        db.delete(current)
    db.commit()
    return {"deleted": True, "name": previous.name, "restored": previous.buy}
