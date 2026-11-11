from ...core.dao import BaseDao
from .model import Plan


class PlanDao(BaseDao[Plan]):
    model = Plan

    def by_code(self, code: str) -> Plan | None:
        return self.find_one(Plan.code == code)

    def ordered(self, public_only: bool = False) -> list[Plan]:
        q = self.query()
        if public_only:
            q = q.filter(Plan.isPublic.is_(True), Plan.isActive.is_(True))
        return q.order_by(Plan.sortOrder, Plan.price).all()

    def cheapest_public(self) -> Plan | None:
        plans = self.ordered(public_only=True)
        return plans[0] if plans else None
