"""Kufunga mwezi: rekodi za mwezi uliofungwa haziwezi kuongezwa, kubadilishwa wala kufutwa."""
from datetime import datetime

from sqlalchemy.orm import Session

from ..core.base_model import utc_now
from ..core.exceptions import BadRequest
from ..core.utils import to_local


def month_of(when: datetime | None) -> str:
    return to_local(when or utc_now()).strftime("%Y-%m")


def is_locked(db: Session, when: datetime | None) -> bool:
    from .model import PeriodLock

    return db.query(PeriodLock.id).filter(PeriodLock.month == month_of(when)).first() is not None


def ensure_open(db: Session, when: datetime | None = None) -> None:
    """`when` = tarehe ya rekodi (None = sasa, kwa rekodi mpya)."""
    if is_locked(db, when):
        m = month_of(when)
        raise BadRequest(f"Mwezi {m[5:]}/{m[:4]} umefungwa na mhasibu - rekodi zake haziwezi kubadilishwa")
