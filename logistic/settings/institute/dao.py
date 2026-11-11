from ...core.dao import BaseDao, to_uuid
from .model import Institute


class InstituteDao(BaseDao[Institute]):
    model = Institute

    def by_account(self, account_no: str) -> Institute | None:
        return self.find_one(Institute.accountNo == account_no)

    def search(self, f) -> list[Institute]:
        criteria = []
        if f.id is not None:
            criteria.append(Institute.id == to_uuid(f.id))
        if f.name is not None:
            criteria.append(Institute.name == f.name)
        if f.accountNo is not None:
            criteria.append(Institute.accountNo == f.accountNo)
        if f.currencyType is not None:
            criteria.append(Institute.currencyType == f.currencyType)
        if f.isBlocked is not None:
            criteria.append(Institute.isBlocked == f.isBlocked)
        return self.find_all(*criteria, order_by=Institute.name)
