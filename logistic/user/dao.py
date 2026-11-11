from sqlalchemy.orm import joinedload

from ..core.dao import BaseDao
from .model import User


class UserDao(BaseDao[User]):
    model = User

    def by_username(self, username: str) -> User | None:
        return self.find_one(User.username == username)

    def by_phone(self, phone: str | None) -> User | None:
        return self.find_one(User.phoneNumber == phone) if phone else None

    def all_with_office(self):
        return self.all(joinedload(User.office))

    def count(self) -> int:
        return self.db.query(User).count()
