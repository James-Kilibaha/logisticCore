"""
SMS za moja kwa moja (vikumbusho) - kila aina ina sheria (AutoSmsRule) inayowekwa na admin kwenye app:

    DEBT            kukumbusha deni la mzigo ulio stoo           (REMAINDER)
    CREDIT          deni la mzigo uliochukuliwa kwa mkopo         (REMAINDER)
    STORAGE_WARN    onyo kabla siku za bure za stoo hazijaisha    (STORAGE_WARN, mara moja)
    STORAGE_OVERDUE mzigo umekaa stoo baada ya siku za bure       (STORAGE_OVERDUE)

Scheduler inaangalia kila saa: sheria iliyowashwa ambayo saa yake imefika na haijaendeshwa leo inaendeshwa.
Kila ankara inapata SMS moja kwa kila kipindi (debts.lastReminderAt / storageWarnedAt / storageRemindedAt).
"""
import logging
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import config
from ..core.base_model import utc_now
from ..core.enums import EInvoiceStatus, EPaymentStatus, ESmsStatus
from ..core.exceptions import BadRequest
from ..core.utils import local_now, whole
from ..invoice.model import Invoice
from ..payment import storage
from ..payment.model import Debt
from . import service as sms_service
from .model import AutoSmsRule

logger = logging.getLogger(__name__)

# aina, (washa, afterDays, everyDays) za mwanzo - zinatoka kwenye .env ya zamani
KINDS = ("DEBT", "CREDIT", "STORAGE_WARN", "STORAGE_OVERDUE")


def _defaults() -> dict[str, dict]:
    return {
        "DEBT": {"enabled": True, "afterDays": config.REMINDER_EVERY_DAYS, "everyDays": config.REMINDER_EVERY_DAYS},
        "CREDIT": {"enabled": True, "afterDays": 3, "everyDays": config.REMINDER_EVERY_DAYS},
        "STORAGE_WARN": {"enabled": True, "afterDays": config.STORAGE_WARN_DAYS, "everyDays": 0},
        "STORAGE_OVERDUE": {"enabled": False, "afterDays": 0, "everyDays": config.STORAGE_ALERT_EVERY_DAYS},
    }


def ensure_defaults(db: Session) -> None:
    have = {r.kind for r in db.query(AutoSmsRule).all()}
    for kind, d in _defaults().items():
        if kind not in have:
            db.add(AutoSmsRule(kind=kind, autoSend=True, hour=config.REMINDER_HOUR, **d))
    db.commit()


def _as_dict(r: AutoSmsRule) -> dict:
    return {"kind": r.kind, "enabled": r.enabled, "afterDays": r.afterDays, "everyDays": r.everyDays,
            "autoSend": r.autoSend, "hour": r.hour,
            "lastRunOn": r.lastRunOn.isoformat() if r.lastRunOn else None}


def rules(db: Session) -> list[dict]:
    ensure_defaults(db)
    rows = {r.kind: r for r in db.query(AutoSmsRule).all()}
    return [_as_dict(rows[k]) for k in KINDS if k in rows]


def update_rules(db: Session, items: list[dict]) -> list[dict]:
    ensure_defaults(db)
    rows = {r.kind: r for r in db.query(AutoSmsRule).all()}
    for item in items:
        kind = (item.get("kind") or "").upper()
        row = rows.get(kind)
        if row is None:
            raise BadRequest(f"Aina ya SMS haijulikani: {kind}")
        for field, low, high in (("afterDays", 0, 365), ("everyDays", 0, 365), ("hour", 0, 23)):
            if item.get(field) is not None:
                value = int(item[field])
                if not low <= value <= high:
                    raise BadRequest(f"{field} iwe kati ya {low} na {high}")
                setattr(row, field, value)
        for field in ("enabled", "autoSend"):
            if item.get(field) is not None:
                setattr(row, field, bool(item[field]))
    db.commit()
    return rules(db)


# ------------------------------------------------------------------------- kazi za kila aina
def _customer(invoice):
    return invoice.customer[0] if invoice.customer else None


def _rows(db: Session, statuses: list[str]):
    return (db.query(Invoice, Debt).join(Debt, Debt.invoice_id == Invoice.id)
            .filter(Invoice.status.in_(statuses)).all())


def _due(last, every_days: int, now) -> bool:
    """Kipindi cha kujirudia kimefika? every_days=0 -> mara moja tu."""
    if last is None:
        return True
    return every_days > 0 and now - last >= timedelta(days=every_days)


def _payment_line() -> str:
    return config.COMPANY_PAYMENT_INFO.splitlines()[0] if config.COMPANY_PAYMENT_INFO else ""


def _debt_text(customer, invoice, debt) -> str:
    extra = f" (pamoja na stoo siku {debt.days})" if debt.storageCharge else ""
    return (f"Habari {customer.name}, tunakukumbusha deni la ankara {invoice.invoiceNumber}: "
            f"TSh {whole(debt.debt)}/={extra}. {_payment_line()} Kwa maelezo piga {config.COMPANY_PHONES}. Ahsante.")


def _run_debt(db: Session, rule: AutoSmsRule, credit: bool, user_id) -> int:
    from ..handover.model import Handover

    now, sent = utc_now(), 0
    statuses = ([EInvoiceStatus.DELIVERED.name, EInvoiceStatus.COMPLETED.name] if credit
                else [EInvoiceStatus.STORE.name])
    handed = {}
    if credit:
        handed = dict(db.query(Handover.invoice_id, func.max(Handover.created_at)).group_by(Handover.invoice_id).all())
    for invoice, debt in _rows(db, statuses):
        customer = _customer(invoice)
        if customer is None or not customer.phoneNumber:
            continue
        if not credit:
            storage.refresh(db, invoice, debt)
        if debt.status == EPaymentStatus.PAID.name or (debt.debt or 0) < 1:
            continue
        since = handed.get(invoice.id) if credit else debt.created_at
        if since is None or now - since < timedelta(days=rule.afterDays):
            continue
        if not _due(debt.lastReminderAt, rule.everyDays, now):
            continue
        text = _debt_text(customer, invoice, debt)
        if credit:
            text = text.replace("tunakukumbusha deni la ankara", "tunakukumbusha deni la mzigo uliochukua (ankara")
            text = text.replace(": TSh", "): TSh", 1)
        if sms_service.queue(db, ESmsStatus.REMAINDER, text=text, msisdn=customer.phoneNumber,
                             reference=invoice.invoiceNumber, invoice_id=invoice.id, logs_id=user_id or invoice.logsId,
                             commit=False, auto=rule.autoSend):
            sent += 1
        debt.lastReminderAt = now
    return sent


def _run_storage_warn(db: Session, rule: AutoSmsRule, user_id) -> int:
    now, sent = utc_now(), 0
    for invoice, debt in _rows(db, [EInvoiceStatus.STORE.name]):
        customer = _customer(invoice)
        if customer is None or not customer.phoneNumber or debt.storageWarnedAt is not None:
            continue
        storage.refresh(db, invoice, debt)
        left = config.DAYS_TO_CHARGE - (debt.days or 0)
        if not 0 < left <= rule.afterDays:
            continue
        text = (f"Habari {customer.name}, mzigo wako (ankara {invoice.invoiceNumber}) umebakiza siku {left} "
                f"za bure stoo. Baada ya hapo kuna gharama ya kuhifadhi ${config.STORAGE_CHARGE_USD:,.2f} "
                f"kwa siku. Tafadhali njoo uchukue. {config.COMPANY_PHONES}")
        if sms_service.queue(db, ESmsStatus.STORAGE_WARN, text=text, msisdn=customer.phoneNumber,
                             reference=invoice.invoiceNumber, invoice_id=invoice.id, logs_id=user_id or invoice.logsId,
                             commit=False, auto=rule.autoSend):
            sent += 1
        debt.storageWarnedAt = now
    return sent


def _run_storage_overdue(db: Session, rule: AutoSmsRule, user_id) -> int:
    now, sent = utc_now(), 0
    for r in storage.overdue(db, min_days=config.DAYS_TO_CHARGE + rule.afterDays, with_customer=True):
        customer = r.get("customer")
        debt = r.get("debt")
        if customer is None or not customer.phoneNumber or debt is None:
            continue
        if not _due(debt.storageRemindedAt, rule.everyDays, now):
            continue
        text = storage.reminder_text(customer.name, r["invoiceNumber"], r["days"], r["storageCharge"], r["chargeUsd"])
        if sms_service.queue(db, ESmsStatus.STORAGE_OVERDUE, text=text, msisdn=customer.phoneNumber,
                             reference=r["invoiceNumber"], invoice_id=debt.invoice_id,
                             logs_id=user_id or debt.logsId, commit=False, auto=rule.autoSend):
            sent += 1
        debt.storageRemindedAt = now
    return sent


def _run_kind(db: Session, rule: AutoSmsRule, user_id) -> int:
    if rule.kind == "DEBT":
        return _run_debt(db, rule, False, user_id)
    if rule.kind == "CREDIT":
        return _run_debt(db, rule, True, user_id)
    if rule.kind == "STORAGE_WARN":
        return _run_storage_warn(db, rule, user_id)
    if rule.kind == "STORAGE_OVERDUE":
        return _run_storage_overdue(db, rule, user_id)
    return 0


def _old_debts_notice(db: Session) -> None:
    """Madeni ya zaidi ya siku 30: taarifa moja kwa siku kwa wasimamizi wa malipo."""
    now = utc_now()
    rows = (db.query(Debt).filter(Debt.status != EPaymentStatus.PAID.name, Debt.debt >= 1,
                                  Debt.created_at < now - timedelta(days=30)).all())
    if rows:
        from ..notification.service import notify

        notify(db, "PAYMENT", "update", kind="DEBT_OLD", link="aging", dedupe_hours=20,
               title=f"Ankara {len(rows)} zina deni la zaidi ya siku 30",
               body=f"Jumla TSh {whole(sum(d.debt or 0 for d in rows))}")


def run(db: Session, user_id=None, kinds: list[str] | None = None) -> dict:
    """Kuendesha sheria zilizowashwa sasa hivi (kitufe "Endesha sasa" / scheduler)."""
    ensure_defaults(db)
    out = {k: 0 for k in KINDS}
    for rule in db.query(AutoSmsRule).filter(AutoSmsRule.enabled.is_(True)).all():
        if kinds is not None and rule.kind not in kinds:
            continue
        out[rule.kind] = _run_kind(db, rule, user_id)
    _old_debts_notice(db)
    db.commit()
    if any(out.values()):
        logger.info("SMS za moja kwa moja: %s", out)
    return {"storageWarnings": out["STORAGE_WARN"], "debtReminders": out["DEBT"],
            "creditReminders": out["CREDIT"], "storageOverdue": out["STORAGE_OVERDUE"]}


def scheduled() -> None:
    """Kila saa: sheria ambazo saa yake imefika na hazijaendeshwa leo."""
    from ..db import session_scope

    now = local_now()
    with session_scope() as db:
        ensure_defaults(db)
        due = [r for r in db.query(AutoSmsRule).filter(AutoSmsRule.enabled.is_(True)).all()
               if now.hour >= r.hour and r.lastRunOn != now.date()]
        if not due:
            return
        run(db, kinds=[r.kind for r in due])
        for r in due:
            r.lastRunOn = now.date()
        db.commit()
