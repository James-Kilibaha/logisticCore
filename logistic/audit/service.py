from sqlalchemy.orm import Session

from . import schema
from .dao import AuditDao


def search(db: Session, f: schema.Search) -> schema.Page:
    total, rows = AuditDao(db).search(f)
    return schema.Page(total=total, items=[schema.Row.model_validate(r) for r in rows])


def modules(db: Session) -> list[str]:
    return AuditDao(db).modules()
