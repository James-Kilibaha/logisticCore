"""
Super admin anaona kinachoendelea kwa kila kampuni:

- `overview(company)` : takwimu za kampuni (wateja, ankara, mabox, malipo, SMS ...) + shughuli zake za karibuni
- `activity(...)`     : mlisho wa shughuli (audit log) wa kampuni zote au moja
- `impersonate(...)`  : token ya KUANGALIA TU kama mtumiaji wa kampuni - super admin anafungua app ya kampuni
                        na kuona kila kitu kama wao; kila kitendo cha kubadilisha kinakataliwa (403 READ_ONLY_VIEW).
                        Kuingia huku kunaandikwa kwenye audit log ya kampuni yenyewe (uwazi).
"""
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import config
from ...core import audit, tenant
from ...core.base_model import utc_now
from ...core.exceptions import BadRequest, NotFound
from ...core.security import create_access_token
from ..company.model import Company
from . import schema
from .dao import MonitorDao


def _month_start():
    return utc_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def overview(db: Session, company: Company) -> dict:
    from ...customer.model import Customer
    from ...expense.model import Expense
    from ...invoice.model import Invoice
    from ...package.model import Package
    from ...payment.model import Payment
    from ...receiver.model import Receiver
    from ...settings.office.model import Office
    from ...sms.model import Sms
    from ...user.model import User

    dao = MonitorDao(db)
    cid = company.id
    month = _month_start()
    week = utc_now() - timedelta(days=7)
    last_login = dao.last_audit(cid, "LOGIN")
    last_action = dao.last_audit(cid)
    users_active = int(db.query(func.count(User.id)).filter(User.company_id == cid, User.active != 0).scalar() or 0)
    return {
        "counts": {
            "customers": dao.count(Customer, cid),
            "customersMonth": dao.count(Customer, cid, month),
            "invoices": dao.count(Invoice, cid),
            "invoicesMonth": dao.count(Invoice, cid, month),
            "receivers": dao.count(Receiver, cid),
            "boxes": dao.count(Package, cid),
            "boxesMonth": dao.count(Package, cid, month),
            "payments": dao.count(Payment, cid),
            "paymentsMonth": dao.count(Payment, cid, month),
            "expensesMonth": dao.count(Expense, cid, month),
            "smsMonth": dao.count(Sms, cid, month),
            "sms": dao.count(Sms, cid),
            "users": users_active,
            "offices": dao.count(Office, cid),
            "actionsWeek": dao.audit_count(cid, week),
        },
        "money": {
            "currency": "TZS",
            "paidMonth": dao.total(Payment.paid, cid, month),
            "paidTotal": dao.total(Payment.paid, cid),
        },
        "lastLogin": {"at": last_login.created_at.isoformat(), "username": last_login.username} if last_login else None,
        "lastActivity": {"at": last_action.created_at.isoformat(), "username": last_action.username,
                         "summary": last_action.summary or f"{last_action.action} {last_action.module}"}
        if last_action else None,
    }


def activity(db: Session, company_id=None, q: str | None = None, module: str | None = None,
             failed: bool | None = None, offset: int = 0, limit: int = 100, kind: str | None = None) -> dict:
    total, rows = MonitorDao(db).activity(company_id, q, module, failed, offset, min(max(limit, 1), 500), kind)
    items = []
    for log, name, slug in rows:
        row = schema.ActivityRow.model_validate(log).model_dump(mode="json")
        row["companyName"], row["companySlug"] = (name, slug) if name else ("Platform", None)
        items.append(row)
    return {"total": total, "items": items}


_last_view: dict[tuple, float] = {}


def track_view(current_user, data: schema.PageView, ip: str | None) -> dict:
    """Ukurasa uliofunguliwa na mtumiaji wa kampuni -> audit log (action VIEW). Super admin anaona kila kitu."""
    import time

    if getattr(current_user, "imp", None):
        return {"recorded": False}  # super admin akiangalia - haihesabiwi kama mtumiaji wa kampuni
    page = data.page.strip().strip("/")[:120]
    key = (str(tenant.company_id()), str(current_user.id), page)
    now = time.time()
    if now - _last_view.get(key, 0) < 20:  # mtumiaji akirudi ukurasa ule ule papo hapo - mara moja tu
        return {"recorded": False}
    _last_view[key] = now
    if len(_last_view) > 20000:
        _last_view.clear()
    title = (data.title or page).strip()[:120]
    audit.write(user_id=current_user.id, username=current_user.username, module=f"page/{page.split('/')[0]}",
                action="VIEW", method="GET", path=f"/{page}", entity_id=None, status_code=200, ip=ip,
                summary=f"Amefungua: {title}", detail=None)
    return {"recorded": True}


def live(db: Session, hours: int = 24) -> list[dict]:
    """Kampuni zilizotumia mfumo ndani ya saa `hours` (idadi ya vitendo + wakati wa mwisho)."""
    since = utc_now() - timedelta(hours=max(hours, 1))
    stats = MonitorDao(db).active_companies_since(since)
    if not stats:
        return []
    companies = {c.id: c for c in db.query(Company).filter(Company.id.in_(list(stats))).all()}
    out = [{"id": str(cid), "name": companies[cid].name, "slug": companies[cid].slug, "actions": n,
            "lastAt": last.isoformat() if last else None}
           for cid, (n, last) in stats.items() if cid in companies]
    return sorted(out, key=lambda r: r["lastAt"] or "", reverse=True)


def impersonate(db: Session, company: Company, data: schema.Impersonate, admin_username: str,
                ip: str | None = None) -> dict:
    """Token ya kuangalia tu (haina refresh token, inaisha baada ya dakika `minutes`)."""
    from ...permission.model import Permission
    from ...user.model import User
    from ..company.service import branding

    if company.status != "ACTIVE":
        raise BadRequest("Kampuni hii haijafunguliwa (inasubiri / imezuiwa) - ithibitishe au ifungue kwanza")
    with tenant.system():
        q = db.query(User).filter(User.company_id == company.id, User.active != 0)
        if data.user_id:
            user = q.filter(User.id == data.user_id).one_or_none()
        else:
            # mtumiaji mwenye ruhusa nyingi zaidi (kawaida ni msimamizi wa kwanza) - anaona kila kitu
            ranked = (db.query(Permission.user_id, func.count(Permission.id).label("n"))
                      .filter(Permission.company_id == company.id).group_by(Permission.user_id).subquery())
            user = (q.outerjoin(ranked, ranked.c.user_id == User.id)
                    .order_by(func.coalesce(ranked.c.n, 0).desc(), User.created_at).first())
    if user is None:
        raise NotFound("Kampuni hii haina mtumiaji hai wa kuangalia kama yeye")
    minutes = min(max(data.minutes, 5), 240)
    claims = {"id": str(user.id), "sub": user.username, "ver": int(user.tokenVersion or 0),
              "cid": str(company.id), "imp": admin_username, "ro": True}
    token = create_access_token(claims, expires_delta=timedelta(minutes=minutes))
    with tenant.use_company(company.id, company.slug):
        audit.write(user_id=None, username=f"{admin_username} (super admin)", module="platform", action="VIEW_AS",
                    method="POST", path="/api/platform/impersonate", entity_id=str(user.id), status_code=200,
                    ip=ip, summary=f"Super admin {admin_username} anaangalia mfumo kama {user.username} (kusoma tu)",
                    detail=None)
    from ...auth.schema import AuthUser

    return {
        "access_token": token,
        "refresh_token": "",
        "token_type": "bearer",
        "expires_in": minutes * 60,
        "readOnly": True,
        "user": AuthUser.model_validate(user).model_dump(mode="json"),
        "company": branding(company),
        "viewer": admin_username,
        "platform": config.PLATFORM_NAME,
    }
