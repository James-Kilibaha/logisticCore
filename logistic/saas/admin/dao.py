from sqlalchemy import func

from ...core.dao import BaseDao
from .model import PlatformAdmin


class PlatformAdminDao(BaseDao[PlatformAdmin]):
    model = PlatformAdmin

    def by_username(self, username: str) -> PlatformAdmin | None:
        return self.find_one(func.lower(PlatformAdmin.username) == (username or "").strip().lower())

    def ordered(self) -> list[PlatformAdmin]:
        return self.query().order_by(PlatformAdmin.fullName).all()

    def count(self) -> int:
        return self.db.query(PlatformAdmin).count()
