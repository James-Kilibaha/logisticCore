"""
Taarifa ndani ya app. Kila tukio linawafikia watumiaji wenye ruhusa husika (mf. malipo -> PAYMENT/update).

    from ..notification.service import notify
    notify(db, "STORE", "select", kind="BOX_ARRIVED", title="Box X limefika", link=f"box:{id}")
"""
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from ..core.base_model import utc_now
from ..core.dao import to_uuid
from ..permission.model import Permission
from ..user.model import User
from .model import Notification

logger = logging.getLogger(__name__)

_FLAG = {"select": Permission.data_select, "insert": Permission.data_insert, "update": Permission.data_update,
         "delete": Permission.data_delete, "block": Permission.data_block}


def recipients(db: Session, module: str, action: str = "select", exclude=None) -> list:
    q = (db.query(User.id).join(Permission, Permission.user_id == User.id)
         .filter(Permission.name == module, _FLAG[action].is_(True), User.active == 1))
    ids = [r[0] for r in q.all()]
    return [i for i in ids if exclude is None or str(i) != str(exclude)]


def notify(db: Session, module: str, action: str = "select", *, kind: str, title: str, body: str | None = None,
           link: str | None = None, exclude=None, dedupe_hours: float | None = None) -> int:
    """Inaandika taarifa (bila commit). `dedupe_hours`: usirudie taarifa ile ile (kind+link) ndani ya muda huo."""
    try:
        if dedupe_hours:
            since = utc_now() - timedelta(hours=dedupe_hours)
            exists = (db.query(Notification.id)
                      .filter(Notification.kind == kind, Notification.link == link, Notification.created_at >= since)
                      .first())
            if exists:
                return 0
        users = recipients(db, module, action, exclude)
        for user_id in users:
            db.add(Notification(user_id=user_id, kind=kind, title=title[:200], body=(body or "")[:500] or None,
                                link=link, isRead=False))
        return len(users)
    except Exception:  # taarifa zisizuie kazi kuu
        logger.exception("Notification failed")
        return 0


def list_for(db: Session, user_id, unread_only: bool = False, limit: int = 30) -> dict:
    q = db.query(Notification).filter(Notification.user_id == to_uuid(user_id))
    unread = q.filter(Notification.isRead.is_(False)).count()
    if unread_only:
        q = q.filter(Notification.isRead.is_(False))
    items = q.order_by(Notification.created_at.desc()).limit(limit).all()
    return {"unread": unread, "items": [
        {"id": str(n.id), "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "isRead": n.isRead,
         "created_at": n.created_at.isoformat() if n.created_at else None} for n in items]}


def mark_read(db: Session, user_id, ids: list | None, all_: bool) -> int:
    q = db.query(Notification).filter(Notification.user_id == to_uuid(user_id), Notification.isRead.is_(False))
    if not all_:
        q = q.filter(Notification.id.in_([to_uuid(i) for i in ids or []]))
    count = q.update({Notification.isRead: True}, synchronize_session=False)
    db.commit()
    return count


def cleanup(days: int = 90) -> None:
    """Scheduler: taarifa zilizosomwa za zamani zinafutwa."""
    from ..db import session_scope

    with session_scope() as db:
        cutoff = utc_now() - timedelta(days=days)
        db.query(Notification).filter(Notification.isRead.is_(True), Notification.created_at < cutoff) \
            .delete(synchronize_session=False)
        db.commit()
