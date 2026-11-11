from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from ..core.dao import BaseDao, to_uuid
from ..core.utils import day_range
from .model import Expense

APPROVED = "APPROVED"


def approved_filter():
    """Matumizi yanayohesabiwa kwenye ripoti (yaliyoidhinishwa)."""
    return or_(Expense.status == APPROVED, Expense.status.is_(None))


class ExpenseDao(BaseDao[Expense]):
    model = Expense

    def search(self, f) -> list[Expense]:
        criteria = []
        if f.id is not None:
            criteria.append(Expense.id == to_uuid(f.id))
        if f.details is not None:
            criteria.append(Expense.details == f.details)
        if f.office_id is not None:
            criteria.append(Expense.office_id == to_uuid(f.office_id))
        for field in ("category_id", "institute_id", "package_id"):
            value = getattr(f, field, None)
            if value:
                criteria.append(getattr(Expense, field) == to_uuid(value))
        status = (getattr(f, "status", None) or "").upper()
        if status:
            criteria.append(approved_filter() if status == APPROVED else Expense.status == status)
        if f.created_at is not None:
            start, end = day_range(f.created_at, f.created_at)
            criteria += [Expense.created_at >= start, Expense.created_at < end]
        start, end = day_range(getattr(f, "startDate", None), getattr(f, "endDate", None))
        if start is not None:
            criteria.append(Expense.created_at >= start)
        if end is not None:
            criteria.append(Expense.created_at < end)
        return self.find_all(*criteria, options=[joinedload(Expense.office)], order_by=Expense.created_at.desc())

    def between(self, start: datetime | None, end: datetime | None, office_id=None) -> list[Expense]:
        """Matumizi yaliyoidhinishwa ndani ya kipindi (ripoti)."""
        criteria = [approved_filter()]
        if office_id is not None:
            criteria.append(Expense.office_id == to_uuid(office_id))
        if start is not None:
            criteria.append(Expense.created_at >= start)
        if end is not None:
            criteria.append(Expense.created_at < end)
        return self.find_all(*criteria, options=[joinedload(Expense.office)], order_by=Expense.created_at)
