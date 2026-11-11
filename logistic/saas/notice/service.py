"""
Taarifa za wasimamizi wa mfumo (super admin) + orodha ya mambo yanayosubiri hatua.

    from ..notice.service import notify
    notify("PAYMENT_SUBMITTED", "PAYMENTS", "Malipo mapya ...", urgent=True, link=f"payment:{id}")

`notify` inatumia session yake (haiathiri transaction ya anayeiita) na haitoi kosa.
Kila msimamizi anaona maeneo ya jukumu lake tu (FINANCE: malipo; SUPPORT: kampuni na msaada; OWNER/VIEWER: yote).
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core import tenant
from ...core.base_model import utc_now
from .model import PlatformNotice

logger = logging.getLogger(__name__)

AREAS = ("PAYMENTS", "COMPANIES", "SUPPORT", "SYSTEM")
_ROLE_AREAS = {
    "OWNER": set(AREAS),
    "VIEWER": {"PAYMENTS", "COMPANIES", "SUPPORT"},
    "FINANCE": {"PAYMENTS", "COMPANIES"},
    "SUPPORT": {"COMPANIES", "SUPPORT"},
}


def areas_for(role: str | None) -> set[str]:
    return _ROLE_AREAS.get((role or "OWNER").upper(), set(AREAS))


def notify(kind: str, area: str, title: str, body: str | None = None, *, link: str | None = None,
           company_id=None, urgent: bool = False, dedupe: str | None = None, dedupe_hours: float = 12) -> bool:
    """Inaandika taarifa mpya. `dedupe`: usirudie taarifa yenye key hii ndani ya `dedupe_hours`."""
    from ...db import SessionLocal

    try:
        with tenant.system():
            db = SessionLocal()
            try:
                if dedupe:
                    since = utc_now() - timedelta(hours=dedupe_hours)
                    if (db.query(PlatformNotice.id)
                            .filter(PlatformNotice.dedupeKey == dedupe, PlatformNotice.created_at >= since).first()):
                        return False
                db.add(PlatformNotice(kind=kind, area=area, priority="URGENT" if urgent else "NORMAL",
                                      title=title[:200], body=(body or "")[:500] or None, link=link,
                                      company_id=_uuid(company_id), dedupeKey=dedupe, readBy=[]))
                db.commit()
                return True
            finally:
                db.close()
    except Exception:
        logger.exception("Platform notice failed")
        return False


def _uuid(value):
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _is_read(n: PlatformNotice, admin_id: str) -> bool:
    return admin_id in (n.readBy or [])


def _out(n: PlatformNotice, admin_id: str) -> dict:
    return {"id": str(n.id), "kind": n.kind, "area": n.area, "priority": n.priority, "title": n.title,
            "body": n.body, "link": n.link, "companyId": str(n.company_id) if n.company_id else None,
            "isRead": _is_read(n, admin_id), "created_at": n.created_at.isoformat() if n.created_at else None}


def list_for(db: Session, admin, limit: int = 40, with_pending: bool = True) -> dict:
    admin_id = str(admin.id)
    areas = areas_for(admin.role)
    since = utc_now() - timedelta(days=60)
    rows = (db.query(PlatformNotice)
            .filter(PlatformNotice.area.in_(areas), PlatformNotice.created_at >= since)
            .order_by(PlatformNotice.created_at.desc()).limit(300).all())
    unread = [n for n in rows if not _is_read(n, admin_id)]
    out = {"unread": len(unread), "urgentUnread": sum(1 for n in unread if n.priority == "URGENT"),
           "items": [_out(n, admin_id) for n in rows[:limit]]}
    if with_pending:
        out["pending"] = pending(db, admin.role)
        out["pendingTotal"] = sum(p["count"] for p in out["pending"])
    return out


def mark_read(db: Session, admin, ids: list | None, all_: bool) -> int:
    admin_id = str(admin.id)
    q = db.query(PlatformNotice).filter(PlatformNotice.area.in_(areas_for(admin.role)))
    if not all_:
        wanted = [u for u in (_uuid(i) for i in ids or []) if u]
        if not wanted:
            return 0
        q = q.filter(PlatformNotice.id.in_(wanted))
    else:
        q = q.filter(PlatformNotice.created_at >= utc_now() - timedelta(days=60))
    count = 0
    for n in q.all():
        if not _is_read(n, admin_id):
            n.readBy = [*(n.readBy or []), admin_id]  # orodha mpya -> SQLAlchemy inaona mabadiliko
            count += 1
    db.commit()
    return count


def pending(db: Session, role: str | None) -> list[dict]:
    """Mambo yanayosubiri hatua sasa hivi (yanahesabiwa moja kwa moja, si kutoka kwenye taarifa)."""
    from ..company.model import Company
    from ..subscription.model import SubscriptionPayment
    from ..support.model import SupportTicket

    areas = areas_for(role)
    items: list[dict] = []

    def add(key, area, count, target, urgent=True):
        if count and area in areas:
            items.append({"key": key, "area": area, "count": int(count), "target": target, "urgent": urgent})

    add("payments", "PAYMENTS",
        db.query(func.count(SubscriptionPayment.id)).filter(SubscriptionPayment.status == "PENDING").scalar(),
        "payments")
    try:
        from ...onlinepay.model import OnlinePayment

        add("onlineUnapplied", "PAYMENTS",
            db.query(func.count(OnlinePayment.id)).filter(OnlinePayment.purpose == "SUBSCRIPTION",
                                                         OnlinePayment.status == "SUCCESS",
                                                         OnlinePayment.applied_id.is_(None)).scalar(),
            "onlinepay")
    except Exception:
        logger.debug("online payments not available", exc_info=True)
    add("signups", "COMPANIES", db.query(func.count(Company.id)).filter(Company.status == "PENDING").scalar(),
        "companies")
    add("tickets", "SUPPORT",
        db.query(func.count(SupportTicket.id)).filter(SupportTicket.unreadAdmin.is_(True),
                                                      SupportTicket.status != "CLOSED").scalar(),
        "support")
    add("ticketsHigh", "SUPPORT",
        db.query(func.count(SupportTicket.id)).filter(SupportTicket.priority == "HIGH",
                                                      SupportTicket.status == "OPEN").scalar(),
        "support")
    if "COMPANIES" in areas or "PAYMENTS" in areas:
        add("expiring", "PAYMENTS" if "PAYMENTS" in areas else "COMPANIES", _expiring_count(db, 3), "dashboard",
            urgent=False)
    if "SYSTEM" in areas:
        add("system", "SYSTEM", _system_problems(), "dashboard")
    return items


def _expiring_count(db: Session, days: int) -> int:
    from ..company.model import Company
    from ..subscription import service as subscriptions

    count = 0
    for (cid,) in db.query(Company.id).filter(Company.status == "ACTIVE").all():
        try:
            st = subscriptions.compute(db, cid)
        except Exception:
            continue
        if st["status"] in ("TRIAL", "ACTIVE", "GRACE") and st["daysLeft"] is not None and st["daysLeft"] <= days:
            count += 1
    return count


def _system_problems() -> int:
    """Matatizo ya server yaliyoripotiwa ndani ya saa 2 zilizopita (kutoka monitor)."""
    from ...db import SessionLocal

    try:
        with tenant.system():
            db = SessionLocal()
            try:
                since = utc_now() - timedelta(hours=2)
                return int(db.query(func.count(PlatformNotice.id))
                           .filter(PlatformNotice.kind == "SYSTEM", PlatformNotice.created_at >= since).scalar() or 0)
            finally:
                db.close()
    except Exception:
        return 0


def scan_expiring() -> int:
    """Scheduler (kila siku): kampuni zinazoisha ndani ya siku 3 - taarifa moja kwa kila kampuni kwa siku."""
    from ...db import SessionLocal
    from ..company.model import Company
    from ..subscription import service as subscriptions

    sent = 0
    with tenant.system():
        db = SessionLocal()
        try:
            for company in db.query(Company).filter(Company.status == "ACTIVE").all():
                st = subscriptions.compute(db, company.id)
                left = st.get("daysLeft")
                if st["status"] not in ("TRIAL", "ACTIVE", "GRACE") or left is None or left > 3:
                    continue
                what = {"TRIAL": "Majaribio", "GRACE": "Muda wa ziada"}.get(st["status"], "Subscription")
                when = "leo" if left <= 0 else f"siku {left}"
                if notify("EXPIRING", "PAYMENTS", f"{company.name}: {what} inaisha {when}",
                          f"{company.slug} · simu {company.phone or '-'}", link=f"company:{company.id}",
                          company_id=company.id, dedupe=f"expiring:{company.id}", dedupe_hours=20):
                    sent += 1
        finally:
            db.close()
    return sent


def cleanup(days: int = 120) -> None:
    from ...db import SessionLocal

    with tenant.system():
        db = SessionLocal()
        try:
            db.query(PlatformNotice).filter(PlatformNotice.created_at < utc_now() - timedelta(days=days)) \
                .delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
