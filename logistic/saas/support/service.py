"""
Tiketi za msaada:
  - kampuni (mtumiaji yeyote) anafungua tiketi -> wewe unapata taarifa (dashboard + email ya PLATFORM_SUPPORT_EMAIL)
  - ukijibu -> aliyefungua na wenye ruhusa ya Mipangilio wanapata taarifa ndani ya app
  - kampuni ikijibu tena, tiketi inarudi OPEN
"""
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import config
from ...core import tenant
from ...core.base_model import utc_now
from ...core.exceptions import BadRequest, NotFound
from .model import SupportTicket, TicketMessage

CATEGORIES = ("TECH", "BILLING", "FEATURE", "OTHER")
STATUSES = ("OPEN", "ANSWERED", "CLOSED")


def _out(t: SupportTicket, company=None) -> dict:
    return {"id": str(t.id), "number": f"T-{t.number:06d}", "subject": t.subject, "category": t.category,
            "priority": t.priority, "status": t.status, "username": t.username,
            "companyId": str(t.company_id), "companyName": getattr(company, "name", None),
            "companySlug": getattr(company, "slug", None),
            "createdAt": t.created_at.isoformat(timespec="seconds") if t.created_at else None,
            "lastMessageAt": t.lastMessageAt.isoformat(timespec="seconds") if t.lastMessageAt else None,
            "unreadAdmin": t.unreadAdmin, "unreadCompany": t.unreadCompany}


def _get(db: Session, ticket_id, company_id=None) -> SupportTicket:
    try:
        pk = uuid.UUID(str(ticket_id))
    except ValueError:
        raise NotFound("Tiketi haipo")
    with tenant.system():
        t = db.get(SupportTicket, pk)
    if t is None or (company_id is not None and t.company_id != company_id):
        raise NotFound("Tiketi haipo")
    return t


def _messages(db: Session, t: SupportTicket) -> list[dict]:
    rows = (db.query(TicketMessage).filter(TicketMessage.ticket_id == t.id)
            .order_by(TicketMessage.created_at.asc()).all())
    return [{"id": str(m.id), "author": m.author, "username": m.username, "text": m.text,
             "at": m.created_at.isoformat(timespec="seconds") if m.created_at else None} for m in rows]


# ------------------------------------------------------------------ kampuni

def create(db: Session, data, user) -> dict:
    from ..company.model import Company

    cid = tenant.require_company_id()
    category = (data.category or "TECH").upper()
    priority = (data.priority or "NORMAL").upper()
    if category not in CATEGORIES or priority not in ("NORMAL", "HIGH"):
        raise BadRequest("Aina au kipaumbele si sahihi")
    now = utc_now()
    with tenant.system():
        number = int(db.query(func.coalesce(func.max(SupportTicket.number), 0)).scalar() or 0) + 1
        t = SupportTicket(number=number, company_id=cid, subject=data.subject.strip(), category=category,
                          priority=priority, status="OPEN", user_id=_uid(user), username=user.username,
                          lastMessageAt=now, unreadAdmin=True, unreadCompany=False)
        db.add(t)
        db.flush()
        db.add(TicketMessage(ticket_id=t.id, author="COMPANY", username=user.username, text=data.text.strip()))
        db.commit()
        company = db.get(Company, cid)
    _email_admin(t, company, data.text)
    from ..notice.service import notify

    notify("TICKET", "SUPPORT", f"Tiketi mpya T-{t.number:06d}: {t.subject}",
           f"{company.name if company else '-'} · {t.username or '-'} · {t.category}"
           + (" · HARAKA" if t.priority == "HIGH" else ""), link=f"ticket:{t.id}", company_id=cid, urgent=True)
    return _out(t, company)


def _uid(user):
    try:
        return uuid.UUID(str(user.id))
    except (TypeError, ValueError, AttributeError):
        return None


def mine(db: Session, status: str | None = None) -> list[dict]:
    cid = tenant.require_company_id()
    with tenant.system():
        q = db.query(SupportTicket).filter(SupportTicket.company_id == cid)
        if status:
            q = q.filter(SupportTicket.status == status.upper())
        return [_out(t) for t in q.order_by(SupportTicket.lastMessageAt.desc()).limit(200).all()]


def view_company(db: Session, ticket_id, mark_read: bool = True) -> dict:
    t = _get(db, ticket_id, tenant.require_company_id())
    with tenant.system():
        if mark_read and t.unreadCompany:
            t.unreadCompany = False
            db.commit()
        return {**_out(t), "messages": _messages(db, t)}


def reply_company(db: Session, ticket_id, data, user) -> dict:
    t = _get(db, ticket_id, tenant.require_company_id())
    with tenant.system():
        db.add(TicketMessage(ticket_id=t.id, author="COMPANY", username=user.username, text=data.text.strip()))
        t.status, t.lastMessageAt, t.unreadAdmin, t.closedAt = "OPEN", utc_now(), True, None
        db.commit()
    from ..notice.service import notify

    notify("TICKET_REPLY", "SUPPORT", f"Jibu jipya kwenye tiketi T-{t.number:06d}: {t.subject}",
           data.text.strip()[:200], link=f"ticket:{t.id}", company_id=t.company_id, urgent=t.priority == "HIGH",
           dedupe=f"ticket-reply:{t.id}", dedupe_hours=0.25)
    return view_company(db, ticket_id, mark_read=False)


def close_company(db: Session, ticket_id) -> dict:
    t = _get(db, ticket_id, tenant.require_company_id())
    with tenant.system():
        t.status, t.closedAt = "CLOSED", utc_now()
        db.commit()
    return _out(t)


def unread_company(db: Session) -> dict:
    cid = tenant.require_company_id()
    with tenant.system():
        n = (db.query(func.count(SupportTicket.id))
             .filter(SupportTicket.company_id == cid, SupportTicket.unreadCompany.is_(True)).scalar())
    return {"unread": int(n or 0)}


# ------------------------------------------------------------------ wewe (super admin)

def admin_list(db: Session, status: str | None = None, company_id=None) -> list[dict]:
    from ..company.model import Company

    q = db.query(SupportTicket)
    if status:
        q = q.filter(SupportTicket.status == status.upper())
    if company_id:
        q = q.filter(SupportTicket.company_id == uuid.UUID(str(company_id)))
    rows = q.order_by(SupportTicket.unreadAdmin.desc(), SupportTicket.lastMessageAt.desc()).limit(300).all()
    companies = {c.id: c for c in db.query(Company).filter(Company.id.in_({t.company_id for t in rows})).all()} \
        if rows else {}
    return [_out(t, companies.get(t.company_id)) for t in rows]


def admin_view(db: Session, ticket_id) -> dict:
    from ..company.model import Company

    t = _get(db, ticket_id)
    if t.unreadAdmin:
        t.unreadAdmin = False
        db.commit()
    return {**_out(t, db.get(Company, t.company_id)), "messages": _messages(db, t)}


def admin_reply(db: Session, ticket_id, data, admin) -> dict:
    t = _get(db, ticket_id)
    db.add(TicketMessage(ticket_id=t.id, author="ADMIN", username=admin.fullName or admin.username,
                         text=data.text.strip()))
    t.status, t.lastMessageAt, t.unreadCompany, t.unreadAdmin, t.closedAt = "ANSWERED", utc_now(), True, False, None
    db.commit()
    _notify_company(t, f"Jibu la msaada: {t.subject}", data.text)
    return admin_view(db, ticket_id)


def admin_status(db: Session, ticket_id, status: str) -> dict:
    status = (status or "").upper()
    if status not in STATUSES:
        raise BadRequest("Hali: OPEN, ANSWERED au CLOSED")
    t = _get(db, ticket_id)
    t.status = status
    t.closedAt = utc_now() if status == "CLOSED" else None
    db.commit()
    if status == "CLOSED":
        _notify_company(t, f"Tiketi imefungwa: {t.subject}", None)
    return admin_view(db, ticket_id)


def admin_counts(db: Session) -> dict:
    open_ = db.query(func.count(SupportTicket.id)).filter(SupportTicket.status == "OPEN").scalar()
    unread = db.query(func.count(SupportTicket.id)).filter(SupportTicket.unreadAdmin.is_(True)).scalar()
    return {"open": int(open_ or 0), "unread": int(unread or 0)}


# ------------------------------------------------------------------ taarifa

def _notify_company(t: SupportTicket, title: str, body: str | None) -> None:
    from ...db import SessionLocal
    from ...notification.model import Notification
    from ...notification.service import notify

    try:
        with tenant.use_company(t.company_id):
            db = SessionLocal()
            try:
                link = f"ticket:{t.id}"
                if t.user_id:
                    db.add(Notification(user_id=t.user_id, kind="SUPPORT_REPLY", title=title[:200],
                                        body=(body or "")[:500] or None, link=link, isRead=False))
                notify(db, "SETTING", "update", kind="SUPPORT_REPLY", title=title, body=body, link=link,
                       exclude=t.user_id)
                db.commit()
            finally:
                db.close()
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Support notification failed")


def _email_admin(t: SupportTicket, company, text: str) -> None:
    from ...core import mail

    if not config.PLATFORM_SUPPORT_EMAIL:
        return
    mail.send_later(config.PLATFORM_SUPPORT_EMAIL,
                    f"[{config.PLATFORM_NAME}] Tiketi T-{t.number:06d}: {t.subject}",
                    f"Kampuni: {company.name} ({company.slug})\nAliyefungua: {t.username}\n"
                    f"Aina: {t.category} · Kipaumbele: {t.priority}\n\n{text}\n\n"
                    f"Jibu kwenye admin panel: Super admin -> Msaada")
