"""
BaseDao - kazi za kawaida za database kwa kila table.

Kila feature ina `dao.py` yake inayorithi `BaseDao` na kuongeza query maalum.
Service haziandiki query moja kwa moja - zinaita dao.
"""
import uuid
from typing import Any, Generic, Iterable, Sequence, Type, TypeVar

from sqlalchemy.orm import Session

T = TypeVar("T")


def to_uuid(value: Any) -> uuid.UUID | None:
    """Inabadilisha string kuwa UUID; inarudisha None kama si UUID halali."""
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


class BaseDao(Generic[T]):
    model: Type[T]

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------ queries
    def query(self, *options):
        q = self.db.query(self.model)
        return q.options(*options) if options else q

    def get(self, id_: Any, *options) -> T | None:
        pk = to_uuid(id_)
        if pk is None:
            return None
        return self.query(*options).filter(self.model.id == pk).one_or_none()

    def find_one(self, *criteria, options: Iterable = ()) -> T | None:
        return self.query(*options).filter(*criteria).first()

    def find_all(self, *criteria, options: Iterable = (), order_by=None) -> Sequence[T]:
        q = self.query(*options).filter(*criteria)
        if order_by is not None:
            q = q.order_by(order_by)
        return q.all()

    def all(self, *options) -> Sequence[T]:
        return self.query(*options).all()

    def exists(self, *criteria) -> bool:
        return self.db.query(self.query().filter(*criteria).exists()).scalar()

    # ------------------------------------------------------------ writes
    def create(self, commit: bool = True, **data) -> T:
        obj = self.model(**data)
        self.db.add(obj)
        if commit:
            self.commit(obj)
        return obj

    def update(self, obj: T, commit: bool = True, **data) -> T:
        for key, value in data.items():
            setattr(obj, key, value)
        self.db.add(obj)
        if commit:
            self.commit(obj)
        return obj

    def save(self, obj: T) -> T:
        self.db.add(obj)
        self.commit(obj)
        return obj

    def delete(self, obj: T) -> bool:
        self.db.delete(obj)
        self.db.commit()
        return True

    def commit(self, obj: T | None = None) -> None:
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        if obj is not None:
            self.db.refresh(obj)
