"""
Taarifa za pop-up: kila aina ina sheria (PopupRule) na swali la database linalorudisha vitu vinavyohusika.
App inauliza /api/popup/due kila dakika; inaonyesha aina ambazo muda wake (everyMinutes) umefika.
Kila mtumiaji anaona aina anazoruhusiwa tu (ruhusa ya moduli husika) na za ofisi yake.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from .. import config
from ..core.base_model import utc_now
from ..core.enums import Action, EInvoiceStatus, EPaymentStatus, Module
from ..core.exceptions import BadRequest
from ..core.permission import allowed
from ..core.scope import office_scope
from ..core.utils import whole
from .model import PopupRule

MAX_ITEMS = 15


@dataclass(frozen=True)
class Kind:
    code: str
    module: Module
    after_days: int
    every_minutes: int
    enabled: bool = True


# Aina zote (na mipangilio ya mwanzo). Mpya zikiongezwa hapa zinaundwa zenyewe backend ikiwaka.
KINDS = [
    Kind("DEBTORS", Module.PAYMENT, 3, 120),
    Kind("STORE_LONG", Module.STORE, config.DAYS_TO_CHARGE, 180),
    Kind("BOX_OPEN", Module.PACKAGE, 5, 240),
    Kind("BOX_LATE", Module.PACKAGE, 0, 360),
    Kind("INVOICE_EMPTY", Module.INVOICE, 2, 240),
    Kind("PARKING_LONG", Module.INVOICE, 5, 240),
    Kind("SMS_FAILED", Module.SMS, 0, 120),
    Kind("SMS_LOW_BALANCE", Module.SMS, 0, 240),
]
BY_CODE = {k.code: k for k in KINDS}


def ensure_defaults(db: Session) -> None:
    have = {r.kind for r in db.query(PopupRule).all()}
    for k in KINDS:
        if k.code not in have:
            db.add(PopupRule(kind=k.code, enabled=k.enabled, afterDays=k.after_days, everyMinutes=k.every_minutes))
    db.commit()


def rules(db: Session) -> list[dict]:
    ensure_defaults(db)
    rows = {r.kind: r for r in db.query(PopupRule).all()}
    return [{"kind": k.code, "module": k.module.value, "enabled": rows[k.code].enabled,
             "afterDays": rows[k.code].afterDays, "everyMinutes": rows[k.code].everyMinutes} for k in KINDS]


def update_rules(db: Session, items: list[dict]) -> list[dict]:
    ensure_defaults(db)
    rows = {r.kind: r for r in db.query(PopupRule).all()}
    for item in items:
        kind = (item.get("kind") or "").upper()
        if kind not in rows:
            raise BadRequest(f"Aina ya taarifa haijulikani: {kind}")
        row = rows[kind]
        if item.get("enabled") is not None:
            row.enabled = bool(item["enabled"])
        if item.get("afterDays") is not None:
            days = int(item["afterDays"])
            if not 0 <= days <= 365:
                raise BadRequest("Siku za kusubiri ziwe kati ya 0 na 365")
            row.afterDays = days
        if item.get("everyMinutes") is not None:
            minutes = int(item["everyMinutes"])
            if not 5 <= minutes <= 10080:
                raise BadRequest("Muda wa kujirudia uwe kati ya dakika 5 na siku 7 (dakika 10080)")
            row.everyMinutes = minutes
    db.commit()
    return rules(db)


# ------------------------------------------------------------------ maswali ya kila aina
def _days(since) -> int:
    return max((utc_now() - since).days, 0) if since else 0


def _office_filter(q, invoice_model, office):
    if office is None:
        return q
    return q.filter(or_(invoice_model.office_id == office, invoice_model.office_id.is_(None)))


def _customer(invoice) -> str:
    c = invoice.customer[0] if invoice.customer else None
    return c.name if c else "-"


def _debtors(db: Session, days: int, office):
    from ..invoice.model import Invoice
    from ..payment.model import Debt

    q = (db.query(Debt, Invoice).join(Invoice, Debt.invoice_id == Invoice.id)
         .options(selectinload(Invoice.customer))
         .filter(Debt.debt >= 1, Debt.status != EPaymentStatus.PAID.name,
                 Invoice.status.notin_([EInvoiceStatus.BLOCKED.name, EInvoiceStatus.BLOCK.name]),
                 Debt.created_at <= utc_now() - timedelta(days=days)))
    q = _office_filter(q, Invoice, office)
    rows = q.order_by(Debt.debt.desc()).all()
    total = sum(d.debt or 0 for d, _ in rows)
    items = [{"title": f"#{inv.invoiceNumber} · {_customer(inv)}",
              "subtitle": f"Deni Tsh {whole(d.debt)}/= · siku {_days(d.created_at)}",
              "link": f"invoice:{inv.id}"} for d, inv in rows[:MAX_ITEMS]]
    return len(rows), items, {"total": round(total)}


def _store_long(db: Session, days: int, office):
    from ..payment import storage

    rows = storage.overdue(db, min_days=days, office=office)
    db.commit()  # siku/gharama za stoo zilizosasishwa
    items = [{"title": f"#{r['invoiceNumber']} · {r['customerName']}",
              "subtitle": f"Siku {r['days']} stoo · gharama ya stoo Tsh {whole(r['storageCharge'])}/=",
              "link": f"invoice:{r['invoiceId']}"} for r in rows[:MAX_ITEMS]]
    return len(rows), items, {}


def _box_open(db: Session, days: int, _office):
    from ..core.utils import split_ids
    from ..package.model import Package

    rows = (db.query(Package)
            .filter(Package.isBoxClose.is_(False), Package.isBlocked.is_(False),
                    Package.created_at <= utc_now() - timedelta(days=days))
            .order_by(Package.created_at).all())
    items = [{"title": f"Box {p.boxId} · {p.packageType}",
              "subtitle": f"Limefunguliwa siku {_days(p.created_at)} · mizigo {len(split_ids(p.productList))}",
              "link": f"box:{p.id}"} for p in rows[:MAX_ITEMS]]
    return len(rows), items, {}


def _box_late(db: Session, days: int, _office):
    from ..core.utils import local_now
    from ..package.model import Package

    today = local_now().date()
    rows = (db.query(Package)
            .filter(Package.isBoxClose.is_(True), Package.isCollect.is_(False), Package.isBlocked.is_(False),
                    Package.eta.isnot(None), Package.eta <= today - timedelta(days=days))
            .order_by(Package.eta).all())
    items = [{"title": f"Box {p.boxId} · {p.packageType}",
              "subtitle": f"Lilitarajiwa {p.eta:%d/%m/%Y} · limechelewa siku {(today - p.eta).days}",
              "link": f"box:{p.id}"} for p in rows[:MAX_ITEMS]]
    return len(rows), items, {}


def _invoice_empty(db: Session, days: int, office):
    from ..invoice.model import Invoice

    q = (db.query(Invoice).options(selectinload(Invoice.customer))
         .filter(Invoice.status == EInvoiceStatus.OPEN.name, ~Invoice.product.any(),
                 Invoice.created_at <= utc_now() - timedelta(days=days)))
    rows = _office_filter(q, Invoice, office).order_by(Invoice.created_at).all()
    items = [{"title": f"#{i.invoiceNumber} · {_customer(i)}",
              "subtitle": f"Imefunguliwa siku {_days(i.created_at)} bila mzigo wowote",
              "link": f"invoice:{i.id}"} for i in rows[:MAX_ITEMS]]
    return len(rows), items, {}


def _parking_long(db: Session, days: int, office):
    from ..invoice.model import Invoice

    since = func.coalesce(Invoice.update_at, Invoice.created_at)
    q = (db.query(Invoice).options(selectinload(Invoice.customer))
         .filter(Invoice.status == EInvoiceStatus.PARKING.name, since <= utc_now() - timedelta(days=days)))
    rows = _office_filter(q, Invoice, office).order_by(since).all()
    items = [{"title": f"#{i.invoiceNumber} · {_customer(i)}",
              "subtitle": f"Tayari kupakiwa siku {_days(i.update_at or i.created_at)} · bado haijawekwa kwenye box",
              "link": f"invoice:{i.id}"} for i in rows[:MAX_ITEMS]]
    return len(rows), items, {}


def _sms_failed(db: Session, days: int, _office):
    from ..sms.model import Sms

    now = utc_now()
    rows = (db.query(Sms)
            .filter(Sms.isReceived.is_(False), Sms.created_at >= now - timedelta(days=7),
                    Sms.created_at <= now - timedelta(days=days),
                    or_((Sms.isSMSSend.is_(False)) & (Sms.error.isnot(None)), Sms.deliveryStatus == "FAILED"))
            .order_by(Sms.created_at.desc()).all())
    items = [{"title": s.msisdn, "subtitle": (s.error or "Haikumfikia mteja")[:120], "link": "sms"}
             for s in rows[:MAX_ITEMS]]
    return len(rows), items, {}


def _sms_low(db: Session, _days: int, _office):
    from ..sms import credit

    s = credit.status(db, ask_gateway=False)
    if not s.get("low"):
        return 0, [], {}
    return 1, [{"title": f"Salio la SMS: {whole(s['balance'])}",
                "subtitle": f"Chini ya kiwango cha onyo ({whole(s['lowAt'])}). Ongeza salio la FastHub.",
                "link": "sms"}], {}


QUERIES: dict[str, Callable] = {
    "DEBTORS": _debtors, "STORE_LONG": _store_long, "BOX_OPEN": _box_open, "BOX_LATE": _box_late,
    "INVOICE_EMPTY": _invoice_empty, "PARKING_LONG": _parking_long, "SMS_FAILED": _sms_failed,
    "SMS_LOW_BALANCE": _sms_low,
}


def due(db: Session, user_id) -> list[dict]:
    """Aina zenye vitu sasa hivi kwa mtumiaji huyu (app inaamua lini kuonyesha kwa everyMinutes)."""
    ensure_defaults(db)
    office = office_scope(db, user_id)
    out = []
    for rule in db.query(PopupRule).filter(PopupRule.enabled.is_(True)).all():
        kind = BY_CODE.get(rule.kind)
        if kind is None or not allowed(db, user_id, kind.module, Action.SELECT):
            continue
        count, items, extra = QUERIES[kind.code](db, rule.afterDays, office)
        if count:
            out.append({"kind": kind.code, "count": count, "afterDays": rule.afterDays,
                        "everyMinutes": rule.everyMinutes, "items": items, **extra})
    order = {k.code: i for i, k in enumerate(KINDS)}
    return sorted(out, key=lambda g: order.get(g["kind"], 99))
