from ...core.dao import BaseDao, to_uuid
from .model import Office


class OfficeDao(BaseDao[Office]):
    model = Office

    def by_name_location(self, name: str, location: str) -> Office | None:
        return self.find_one(Office.name == name, Office.location == location)

    def search(self, f) -> list[Office]:
        criteria = []
        if f.id is not None:
            criteria.append(Office.id == to_uuid(f.id))
        if f.name is not None:
            criteria.append(Office.name == f.name)
        if f.location is not None:
            criteria.append(Office.location == f.location)
        if f.phoneNumber is not None:
            criteria.append(Office.phoneNumber == f.phoneNumber)
        if f.isBlocked is not None:
            criteria.append(Office.isBlocked == f.isBlocked)
        return self.find_all(*criteria, order_by=Office.name)
