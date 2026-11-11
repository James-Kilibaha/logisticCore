"""
Dashibodi ya shughuli za mtumiaji: alichofanya kwenye mfumo kwa kipindi fulani.

- Kila mtumiaji anaona shughuli ZAKE tu, na vipimo vya moduli anazoruhusiwa kuona (ruhusa ya select).
- Mwenye ruhusa ya kumbukumbu za vitendo (AUDIT select - kawaida admin) anaweza kuona za mtumiaji yeyote.
"""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..audit.model import AuditLog
from ..core.enums import Action, Module
from ..core.exceptions import BadRequest, NotFound, PermissionDenied
from ..core.permission import allowed
from ..core.dao import to_uuid
from ..core.utils import local_now, local_tz, to_local

MAX_DAYS = 366


def _utc(d: date) -> datetime:
    """Mwanzo wa siku (saa za ofisi) -> UTC bila tzinfo (kama tunavyohifadhi)."""
    return datetime.combine(d, time.min, tzinfo=local_tz()).astimezone(timezone.utc).replace(tzinfo=None)


def _range(start: str | None, end: str | None) -> tuple[date, date]:
    today = local_now().date()
    try:
        last = date.fromisoformat(end) if end else today
        first = date.fromisoformat(start) if start else last - timedelta(days=29)
    except ValueError:
        raise BadRequest("Tarehe ziwe kwa muundo YYYY-MM-DD")
    if first > last:
        first, last = last, first
    if (last - first).days > MAX_DAYS:
        raise BadRequest(f"Kipindi kisizidi siku {MAX_DAYS}")
    return first, last


def _metrics(db: Session, viewer, user_id, since: datetime, until: datetime) -> list[dict]:
    from ..claim.model import CargoClaim
    from ..expense.model import Expense
    from ..handover.model import Handover
    from ..invoice.model import Invoice
    from ..package.model import Package
    from ..payment.model import Payment
    from ..product.model import Product
    from ..quotation.model import Quotation
    from ..sms.model import Sms

    def can(module: Module) -> bool:
        return allowed(db, viewer, module, Action.SELECT)

    def window(model):
        return (model.logsId == user_id, model.created_at >= since, model.created_at < until)

    out = []
    if can(Module.INVOICE):
        out.append({"key": "invoices", "count": db.query(func.count(Invoice.id)).filter(*window(Invoice)).scalar()})
    if can(Module.PRODUCT) or can(Module.RECEIVE):
        n, kg = db.query(func.count(Product.id), func.coalesce(func.sum(Product.weight), 0)).filter(
            *window(Product)).one()
        out.append({"key": "products", "count": n, "weight": round(float(kg or 0), 1)})
    if can(Module.PACKAGE):
        out.append({"key": "boxes", "count": db.query(func.count(Package.id)).filter(*window(Package)).scalar()})
    if can(Module.PAYMENT):
        rows = (db.query(Payment.kind, func.count(Payment.id), func.coalesce(func.sum(Payment.paid), 0))
                .filter(*window(Payment)).group_by(Payment.kind).all())
        by = {k or "PAYMENT": (n, float(s or 0)) for k, n, s in rows}
        pay = by.get("PAYMENT", (0, 0.0))
        out.append({"key": "payments", "count": pay[0], "amount": round(pay[1])})
        if "REFUND" in by:
            out.append({"key": "refunds", "count": by["REFUND"][0], "amount": round(by["REFUND"][1])})
    if can(Module.HANDOVER):
        out.append({"key": "handovers", "count": db.query(func.count(Handover.id)).filter(*window(Handover)).scalar()})
    if can(Module.EXPENSES):
        n, s = db.query(func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0)).filter(
            *window(Expense)).one()
        out.append({"key": "expenses", "count": n, "amount": round(float(s or 0))})
    if can(Module.QUOTE):
        out.append({"key": "quotations",
                    "count": db.query(func.count(Quotation.id)).filter(*window(Quotation)).scalar()})
    if can(Module.CLAIM):
        out.append({"key": "claims", "count": db.query(func.count(CargoClaim.id)).filter(*window(CargoClaim)).scalar()})
    if can(Module.SMS):
        out.append({"key": "sms", "count": db.query(func.count(Sms.id)).filter(*window(Sms)).scalar()})
    return out


def summary(db: Session, viewer, user_id=None, start: str | None = None, end: str | None = None) -> dict:
    from ..user.model import User

    can_others = allowed(db, viewer, Module.AUDIT, Action.SELECT)
    target = to_uuid(user_id) if user_id else to_uuid(viewer)
    if str(target) != str(viewer) and not can_others:
        raise PermissionDenied("Unaweza kuona shughuli zako tu")
    user = db.get(User, target)
    if user is None:
        raise NotFound("Mtumiaji hayupo")

    first, last = _range(start, end)
    since, until = _utc(first), _utc(last + timedelta(days=1))

    logs = (db.query(AuditLog).filter(AuditLog.user_id == target, AuditLog.created_at >= since,
                                      AuditLog.created_at < until)
            .order_by(AuditLog.created_at.desc()).limit(5000).all())
    per_day = Counter(to_local(r.created_at).date().isoformat() for r in logs if r.created_at)
    days = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    modules = Counter(r.module for r in logs if r.status_code < 400)
    devices = Counter(f"{r.client or '-'}|{r.device or '-'}" for r in logs if r.client or r.device)
    failed = sum(1 for r in logs if r.status_code >= 400)
    logins = sum(1 for r in logs if r.module == "auth" and r.action == "LOGIN" and r.status_code < 400)

    return {
        "user": {"id": str(user.id), "username": user.username, "name": f"{user.firstName} {user.lastName}".strip()},
        "self": str(target) == str(viewer),
        "canViewOthers": can_others,
        "start": first.isoformat(), "end": last.isoformat(),
        "actions": len(logs) - failed, "failed": failed, "logins": logins,
        "metrics": _metrics(db, viewer, target, since, until),
        "daily": [{"date": d, "count": per_day.get(d, 0)} for d in days],
        "modules": [{"module": m, "count": n} for m, n in modules.most_common(12)],
        "devices": [{"client": k.split("|")[0], "device": k.split("|", 1)[1], "count": n}
                    for k, n in devices.most_common(5)],
        "recent": [{"id": str(r.id), "created_at": r.created_at.isoformat() if r.created_at else None,
                    "module": r.module, "action": r.action, "summary": r.summary, "path": r.path,
                    "statusCode": r.status_code, "client": r.client, "device": r.device} for r in logs[:40]],
    }
