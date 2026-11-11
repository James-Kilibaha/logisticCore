"""
Gharama za kuhifadhi mzigo stoo.

Mzigo ukifika stoo (status STORE) saa inaanza. Baada ya siku DAYS_TO_CHARGE za bure, kila siku
inatozwa STORAGE_CHARGE_USD (inabadilishwa kuwa TSh kwa kiwango cha USD kilichopo).
Gharama inaacha kuongezeka mzigo ukikabidhiwa (status inatoka STORE).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import config
from ..core.enums import EInvoiceStatus
from ..core.utils import local_now, local_tz, to_local
from ..settings.currency.dao import CurrencyDao
from ..settings.currency.model import Currency

logger = logging.getLogger(__name__)

LOCAL_CODES = {"TZS", "TSH", "TSHS", "TSHS.", "TSH."}


def usd_rate(db: Session) -> float:
    return currency_rate(db, "USD") or 0.0


def currency_rate(db: Session, code: str) -> float | None:
    """TSh kwa 1 ya sarafu hii (kiwango kinachotumika sasa). TSh yenyewe = 1."""
    code = (code or "TZS").strip().upper()
    if code in LOCAL_CODES:
        return 1.0
    active = CurrencyDao(db).active_by_name(code)
    if active:
        return float(active[0].buy or 0) or None
    latest = (db.query(Currency).filter(Currency.name == code).order_by(Currency.created_at.desc()).first())
    return float(latest.buy) if latest and latest.buy else None


def arrival(invoice, debt=None) -> datetime | None:
    """Muda (UTC) mzigo ulipofika stoo: kutoka `history` (STORE_...), au deni lilipofunguliwa."""
    if debt is not None and debt.storageFrom:
        return debt.storageFrom
    stamps = [h for h in (invoice.history or "").split(",") if h.startswith(f"{EInvoiceStatus.STORE.name}_")]
    if stamps:
        try:
            local = datetime.strptime(stamps[-1].split("_", 1)[1][:19], "%Y-%m-%dT%H:%M:%S")
            return local.replace(tzinfo=local_tz()).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            pass
    return debt.created_at if debt is not None else None


def days_in_store(start_utc: datetime | None) -> int:
    if start_utc is None:
        return 0
    return max((local_now().date() - to_local(start_utc).date()).days, 0)


def chargeable_days(days: int) -> int:
    return max(days - config.DAYS_TO_CHARGE, 0)


def refresh(db: Session, invoice, debt) -> bool:
    """
    Inasasisha siku na gharama za stoo za deni hili (kama mzigo bado uko stoo).
    Inarudisha True kama kitu kimebadilika (haifanyi commit).
    """
    if debt is None or invoice is None or invoice.status != EInvoiceStatus.STORE.name:
        return False
    start = arrival(invoice, debt)
    if start is None:
        return False
    days = days_in_store(start)
    charge = round(chargeable_days(days) * config.STORAGE_CHARGE_USD * usd_rate(db))
    changed = debt.storageFrom != start or (debt.days or 0) != days or (debt.storageCharge or 0) != charge
    if changed:
        debt.storageFrom = start
        debt.days = days
        debt.storageCharge = charge
        from .service import recalculate

        recalculate(db, debt)
    return changed


# ------------------------------------------------------------- mizigo iliyochelewa stoo
def overdue(db: Session, min_days: int | None = None, office=None, with_customer: bool = False) -> list[dict]:
    """
    Ankara zilizo stoo zaidi ya siku za bure (au `min_days`), za zamani kwanza.
    Inasasisha siku/gharama za stoo kabla ya kurudisha (haifanyi commit).
    """
    from sqlalchemy.orm import selectinload

    from ..invoice.model import Invoice
    from ..payment.model import Debt

    limit = config.DAYS_TO_CHARGE if min_days is None else max(min_days, 0)
    q = (db.query(Invoice, Debt).join(Debt, Debt.invoice_id == Invoice.id)
         .options(selectinload(Invoice.customer))
         .filter(Invoice.status == EInvoiceStatus.STORE.name))
    if office is not None:
        q = q.filter((Invoice.office_id == office) | (Invoice.office_id.is_(None)))
    rate = usd_rate(db)
    out = []
    for invoice, debt in q.all():
        refresh(db, invoice, debt)
        days = debt.days or 0
        if days <= limit:
            continue
        customer = invoice.customer[0] if invoice.customer else None
        extra = chargeable_days(days)
        row = {
            "invoiceId": str(invoice.id), "invoiceNumber": invoice.invoiceNumber,
            "customerId": str(customer.id) if customer else None,
            "customerName": customer.name if customer else "-", "phone": (customer.phoneNumber if customer else None) or "",
            "days": days, "chargeableDays": extra, "chargeUsd": round(extra * config.STORAGE_CHARGE_USD, 2),
            "storageCharge": round(debt.storageCharge or 0, 2), "balance": round(debt.debt or 0, 2),
            "arrivedAt": debt.storageFrom.isoformat(timespec="minutes") if debt.storageFrom else None,  # UTC
            "remindedAt": debt.storageRemindedAt.isoformat(timespec="minutes") if debt.storageRemindedAt else None,
            "usdRate": rate,
        }
        if with_customer:
            row["customer"], row["debt"], row["invoice"] = customer, debt, invoice
        out.append(row)
    out.sort(key=lambda r: -r["days"])
    return out


def overdue_summary(db: Session, office=None) -> dict:
    rows = overdue(db, office=office)
    return {"freeDays": config.DAYS_TO_CHARGE, "chargePerDayUsd": config.STORAGE_CHARGE_USD,
            "alertEveryDays": config.STORAGE_ALERT_EVERY_DAYS, "count": len(rows),
            "totalCharge": round(sum(r["storageCharge"] for r in rows), 2),
            "totalUsd": round(sum(r["chargeUsd"] for r in rows), 2), "items": rows}


def reminder_text(name: str | None, invoice_number: str, days: int, charge_tsh: float, charge_usd: float) -> str:
    from ..core.utils import whole

    return (f"Habari {name or ''}, mzigo wako (ankara {invoice_number}) umekaa stoo siku {days}. "
            f"Baada ya siku {config.DAYS_TO_CHARGE} za bure, kila siku inatozwa ${config.STORAGE_CHARGE_USD:,.2f}. "
            f"Gharama ya stoo hadi leo: ${charge_usd:,.2f} (TSh {whole(charge_tsh)}/=). "
            f"Tafadhali njoo uchukue mzigo wako mapema. {config.COMPANY_PHONES}")


def alert_overdue() -> None:
    """Scheduler: taarifa (popup) kwenye app kila STORAGE_ALERT_EVERY_DAYS kama kuna mizigo iliyochelewa stoo."""
    from ..core.utils import whole
    from ..db import session_scope
    from ..notification.service import notify

    every = max(config.STORAGE_ALERT_EVERY_DAYS, 1)
    with session_scope() as db:
        rows = overdue(db)
        if rows:
            notify(db, "STORE", "select", kind="STORAGE_OVERDUE", link="store-overdue",
                   dedupe_hours=every * 24 - 1,
                   title=f"Mizigo {len(rows)} imekaa stoo zaidi ya siku {config.DAYS_TO_CHARGE}",
                   body=f"Gharama ya stoo hadi sasa: TSh {whole(sum(r['storageCharge'] for r in rows))}. "
                        f"Wa zamani zaidi: {rows[0]['customerName']} siku {rows[0]['days']}.")
        db.commit()


# --------------------------------------------------------------- mapato ya stoo
def storage_income(db: Session, start: datetime | None, end: datetime | None, office=None) -> dict:
    """
    Mapato ya kipindi yakigawanywa: usafirishaji na stoo.

    Kwa kila deni, malipo yanalipa kwanza gharama ya usafirishaji (amount - discount); kinachozidi kinahesabiwa
    kuwa malipo ya stoo (hadi storageCharge). Refund inapunguza kwa njia ile ile.
    """
    from sqlalchemy.orm import selectinload

    from ..core.enums import EPaymentKind
    from ..invoice.model import Invoice
    from ..payment.model import Debt, Payment

    def scoped(q):
        if office is not None:
            q = q.filter((Invoice.office_id == office) | (Invoice.office_id.is_(None)))
        return q

    def in_period(p):
        return (start is None or p.created_at >= start) and (end is None or p.created_at < end)

    def signed(p):
        return (p.paid or 0) * (-1 if p.kind == EPaymentKind.REFUND.name else 1)

    # jumla ya malipo yote ya kipindi
    pq = scoped(db.query(Payment).join(Debt, Debt.id == Payment.debt_id).join(Invoice, Invoice.id == Debt.invoice_id))
    if start is not None:
        pq = pq.filter(Payment.created_at >= start)
    if end is not None:
        pq = pq.filter(Payment.created_at < end)
    total = sum(signed(p) for p in pq.all())

    rows = []
    debts = scoped(db.query(Debt, Invoice).join(Invoice, Invoice.id == Debt.invoice_id)
                   .options(selectinload(Invoice.customer)).filter(Debt.storageCharge > 0)).all()
    if debts:
        pays: dict = {}
        for p in (db.query(Payment).filter(Payment.debt_id.in_([d.id for d, _ in debts]))
                  .order_by(Payment.created_at)):
            pays.setdefault(p.debt_id, []).append(p)
        for d, inv in debts:
            freight = max((d.amount or 0) - (d.discount or 0), 0)
            cap = d.storageCharge or 0
            cum = got = 0.0
            last = None
            for p in pays.get(d.id, []):
                before = min(max(cum - freight, 0), cap)
                cum += signed(p)
                part = min(max(cum - freight, 0), cap) - before
                if in_period(p) and part:
                    got += part
                    last = p.created_at
            if abs(got) >= 0.5:
                c = inv.customer[0] if inv.customer else None
                rows.append({"invoiceId": str(inv.id), "invoiceNumber": inv.invoiceNumber,
                             "customerName": c.name if c else "-", "days": d.days or 0,
                             "storageCharge": round(cap, 2), "collected": round(got, 2),
                             "paidAt": last.isoformat(timespec="minutes") if last else None,  # UTC
                             "status": inv.status})
    rows.sort(key=lambda r: r["paidAt"] or "", reverse=True)
    collected = sum(r["collected"] for r in rows)
    pending = sum(d.storageCharge or 0 for d, inv in debts if inv.status == EInvoiceStatus.STORE.name)
    return {"total": round(total, 2), "freight": round(total - collected, 2), "storage": round(collected, 2),
            "collected": round(collected, 2), "invoices": len(rows), "pendingInStore": round(pending, 2),
            "items": rows}
