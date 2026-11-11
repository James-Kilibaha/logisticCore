from sqlalchemy.orm import joinedload

from ...core.dao import BaseDao, to_uuid
from .model import Price


class PriceDao(BaseDao[Price]):
    model = Price

    def active_same(self, name: str, weight: float, unit: str = "KG") -> list[Price]:
        return self.find_all(Price.name == name, Price.weight == weight, Price.unit == unit,
                             Price.isBlocked.is_(False))

    def search(self, f) -> list[Price]:
        criteria = []
        if f.id is not None:
            criteria.append(Price.id == to_uuid(f.id))
        if f.name is not None:
            criteria.append(Price.name == f.name)
        if f.isBlocked is not None:
            criteria.append(Price.isBlocked == f.isBlocked)
        if getattr(f, "unit", None):
            criteria.append(Price.unit == f.unit.upper())
        return self.find_all(*criteria, options=[joinedload(Price.currency)], order_by=Price.created_at.desc())

    def repoint_active(self, name: str, currency_id) -> None:
        """Bei zote zisizozuiwa za sarafu [name] zinaelekezwa kwenye kiwango kipya."""
        for price in self.find_all(Price.name == name, Price.isBlocked.is_(False)):
            price.currency_id = currency_id
            self.db.add(price)
