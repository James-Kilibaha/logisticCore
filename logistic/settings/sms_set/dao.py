from ...core.dao import BaseDao
from .model import SmsSet


class SmsSetDao(BaseDao[SmsSet]):
    model = SmsSet

    def by_name(self, name: str) -> SmsSet | None:
        return self.find_one(SmsSet.name == name)

    def is_enabled(self, name: str) -> bool:
        return self.exists(SmsSet.name == name, SmsSet.action.is_(True))

    def ordered(self) -> list[SmsSet]:
        return self.find_all(order_by=SmsSet.name)
