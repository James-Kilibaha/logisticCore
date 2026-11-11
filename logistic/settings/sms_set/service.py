from sqlalchemy.orm import Session

from ...core.enums import ESmsStatus
from ...core.exceptions import NotFound
from .dao import SmsSetDao
from .model import SmsSet


def create_missing(db: Session) -> list[SmsSet]:
    """Inaunda mipangilio ya SMS ambayo bado haipo (zote zinaanza zikiwa zimewashwa)."""
    dao = SmsSetDao(db)
    for status in ESmsStatus:
        if status is ESmsStatus.CUSTOM:  # aina ya zamani - ujumbe wa mkono sasa una aina zake (BROADCAST, ...)
            continue
        if dao.by_name(status.name) is None:
            dao.create(commit=False, name=status.name, action=True)
    db.commit()
    return dao.ordered()


def list_all(db: Session) -> list[SmsSet]:
    return SmsSetDao(db).ordered()


def toggle(db: Session, sms_set_id) -> SmsSet:
    dao = SmsSetDao(db)
    item = dao.get(sms_set_id)
    if item is None:
        raise NotFound("No Sms Set Exited..")
    return dao.update(item, action=not item.action)


def is_enabled(db: Session, name: str) -> bool:
    return SmsSetDao(db).is_enabled(name)
