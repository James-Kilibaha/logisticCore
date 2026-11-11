from ...core.dao import BaseDao, to_uuid
from .model import Currency


class CurrencyDao(BaseDao[Currency]):
    model = Currency

    def active_by_name(self, name: str) -> list[Currency]:
        return self.find_all(Currency.name == name, Currency.isBlocked.is_(False))

    def search(self, f) -> list[Currency]:
        criteria = []
        if f.id is not None:
            criteria.append(Currency.id == to_uuid(f.id))
        if f.name is not None:
            criteria.append(Currency.name == f.name)
        if f.isBlocked is not None:
            criteria.append(Currency.isBlocked == f.isBlocked)
        return self.find_all(*criteria, order_by=Currency.created_at.desc())
