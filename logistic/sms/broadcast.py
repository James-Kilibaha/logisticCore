"""
Ujumbe kwa wateja (SMS na/au WhatsApp) ulioandikwa na mtumiaji: kwa mteja mmoja, waliochaguliwa au wote.

Walengwa (audience):
    ALL        - wateja wote walio hai (active)
    SELECTED   - wateja waliochaguliwa (customerIds)
    ONE        - mteja mmoja (customerId) au namba yoyote (phone)
    IN_STORE   - wateja wenye mzigo stoo sasa hivi
    OVERDUE    - wateja wenye mzigo uliokaa stoo zaidi ya siku za bure (DAYS_TO_CHARGE)
    DEBT       - wateja wanaodaiwa

Maandishi yanaweza kuwa na {jina} - linabadilishwa kuwa jina la kila mteja.
"""
import logging
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core import tenant
from .. import config
from ..core.enums import EInvoiceStatus, EPaymentStatus, ESmsStatus
from ..core.exceptions import BadRequest
from ..core.phone import normalize as normalize_phone, try_normalize
from ..customer.model import Customer
from ..invoice.model import Invoice
from ..payment.model import Debt
from .dao import SmsDao

logger = logging.getLogger(__name__)

AUDIENCES = ("ALL", "SELECTED", "ONE", "IN_STORE", "OVERDUE", "DEBT")
CHANNELS = ("SMS", "WHATSAPP", "BOTH")


class Broadcast(BaseModel):
    audience: str = "ALL"
    customerIds: list[UUID] = Field(default_factory=list)
    customerId: UUID | None = None
    phone: str | None = None
    name: str | None = None
    text: str = ""
    channel: str = "SMS"
    sendNow: bool = True


def personalise(text: str, name: str | None) -> str:
    first = (name or "").strip()
    return text.replace("{jina}", first).replace("{JINA}", first).replace("{name}", first).strip()


def segments(text: str) -> int:
    """Idadi ya SMS (vipande) kwa ujumbe mmoja: 160 herufi (GSM) au 153 kwa kila kipande zikizidi."""
    n = len(text or "")
    if n <= 160:
        return 1
    return -(-n // 153)


def _invoice_customers(db: Session, *criteria, office=None) -> list[Customer]:
    q = (db.query(Customer).join(Customer.invoice).join(Debt, Debt.invoice_id == Invoice.id)
         .filter(Customer.active == 1, *criteria))
    if office is not None:
        q = q.filter((Invoice.office_id == office) | (Invoice.office_id.is_(None)))
    return q.distinct().all()


def recipients(db: Session, data: Broadcast, office=None) -> list[tuple[str, str, UUID | None]]:
    """[(jina, simu, customer_id)] bila kurudia namba ile ile."""
    audience = (data.audience or "ALL").upper()
    if audience not in AUDIENCES:
        raise BadRequest(f"audience must be one of {', '.join(AUDIENCES)}")
    if audience == "ALL":
        customers = db.query(Customer).filter(Customer.active == 1).order_by(Customer.name).all()
    elif audience == "SELECTED":
        if not data.customerIds:
            raise BadRequest("Chagua angalau mteja mmoja")
        customers = db.query(Customer).filter(Customer.id.in_(data.customerIds)).order_by(Customer.name).all()
    elif audience == "ONE":
        if data.customerId:
            customers = db.query(Customer).filter(Customer.id == data.customerId).all()
        elif data.phone and data.phone.strip():
            return [((data.name or "").strip(), normalize_phone(data.phone), None)]
        else:
            raise BadRequest("Weka mteja au namba ya simu")
    elif audience == "IN_STORE":
        customers = _invoice_customers(db, Invoice.status == EInvoiceStatus.STORE.name, office=office)
    elif audience == "OVERDUE":
        from ..payment import storage

        customers = [r["customer"] for r in storage.overdue(db, office=office, with_customer=True) if r["customer"]]
    else:  # DEBT
        customers = _invoice_customers(db, Debt.status != EPaymentStatus.PAID.name, Debt.debt >= 1,
                                       Invoice.status.notin_([EInvoiceStatus.BLOCKED.name, EInvoiceStatus.BLOCK.name]),
                                       office=office)
    out, seen = [], set()
    for c in customers:
        phone = try_normalize(c.phoneNumber)  # wasio na namba (au namba mbovu) wanarukwa
        if not phone or phone in seen:
            continue
        seen.add(phone)
        out.append((c.name, phone, c.id))
    return out


def preview(db: Session, data: Broadcast, office=None) -> dict:
    people = recipients(db, data, office)
    sample = personalise(data.text or "", people[0][0] if people else "")
    parts = segments(sample)
    return {"count": len(people), "segments": parts, "totalSms": parts * len(people), "sample": sample,
            "recipients": [{"name": n, "phone": p, "customerId": str(c) if c else None} for n, p, c in people[:200]]}


def dispatch(ids: list) -> None:
    """Kutuma kwa nyuma (thread) - tests zinaweza kuibadilisha."""
    from .service import send_pending_ids

    tenant.spawn(send_pending_ids, list(ids))


def send(db: Session, data: Broadcast, user_id, office=None, kind: ESmsStatus = ESmsStatus.BROADCAST,
         reference: str | None = None, invoice_for: dict | None = None) -> dict:
    """Inaandaa ujumbe kwa kila mlengwa na (kama sendNow) inautuma mara moja kwa nyuma."""
    from .service import ensure_enabled

    ensure_enabled(db, kind)
    text = (data.text or "").strip()
    if not text:
        raise BadRequest("Andika ujumbe")
    if len(text) > 1000:
        raise BadRequest("Ujumbe ni mrefu sana (herufi 1000 mwisho)")
    channel = (data.channel or "SMS").upper()
    if channel not in CHANNELS:
        raise BadRequest("channel must be SMS, WHATSAPP or BOTH")
    if channel in ("WHATSAPP", "BOTH") and not config.WHATSAPP_ENABLED:
        raise BadRequest("WhatsApp haijawekwa (WHATSAPP_ENABLED kwenye .env)")
    people = recipients(db, data, office)
    if not people:
        raise BadRequest("Hakuna mteja mwenye namba ya simu kwa walengwa hawa")
    if len(people) > config.BROADCAST_MAX:
        raise BadRequest(f"Walengwa ni wengi mno ({len(people)}); mwisho ni {config.BROADCAST_MAX} kwa mara moja")

    ref = reference or f"UJUMBE-{datetime.now():%Y%m%d%H%M}"
    channels = ["SMS", "WHATSAPP"] if channel == "BOTH" else [channel]
    dao = SmsDao(db)
    ids = []
    for name, phone, customer_id in people:
        body = personalise(text, name)
        for ch in channels:
            sms = dao.create(commit=False, text=body, msisdn=phone,
                             source=config.SMS_SOURCE_NAME if ch == "SMS" else "WhatsApp",
                             reference=ref, coding=config.SMS_CODING if ch == "SMS" else "UTF8",
                             smsFor=kind.name, isReceived=False, isSMSSend=False, channel=ch,
                             invoice_id=(invoice_for or {}).get(customer_id), logsId=user_id)
            ids.append(sms)
    db.flush()
    ids = [s.id for s in ids]
    db.commit()
    if data.sendNow:
        dispatch(ids)
    logger.info("Ujumbe %s: walengwa %s, ujumbe %s (%s)", ref, len(people), len(ids), channel)
    return {"reference": ref, "recipients": len(people), "messages": len(ids), "sending": bool(data.sendNow),
            "channel": channel}


# ------------------------------------------------------ kukumbusha mizigo iliyochelewa stoo
class RemindOverdue(BaseModel):
    invoiceIds: list[UUID] = Field(default_factory=list)  # tupu = zote zilizochelewa
    channel: str = "SMS"
    text: str | None = None  # hiari: {jina} {ankara} {siku} {usd} {tsh}
    sendNow: bool = True


def remind_overdue(db: Session, data: RemindOverdue, user_id, office=None) -> dict:
    from ..core.base_model import utc_now
    from ..core.utils import whole
    from ..payment import storage

    from .service import ensure_enabled

    ensure_enabled(db, ESmsStatus.STORAGE_OVERDUE)
    channel = (data.channel or "SMS").upper()
    if channel not in CHANNELS:
        raise BadRequest("channel must be SMS, WHATSAPP or BOTH")
    if channel in ("WHATSAPP", "BOTH") and not config.WHATSAPP_ENABLED:
        raise BadRequest("WhatsApp haijawekwa (WHATSAPP_ENABLED kwenye .env)")
    wanted = {str(i) for i in data.invoiceIds}
    rows = [r for r in storage.overdue(db, office=office, with_customer=True)
            if (not wanted or r["invoiceId"] in wanted) and try_normalize(r["phone"])]
    for r in rows:
        r["phone"] = try_normalize(r["phone"])
    if not rows:
        raise BadRequest("Hakuna mzigo uliochelewa stoo wenye namba ya mteja")
    channels = ["SMS", "WHATSAPP"] if channel == "BOTH" else [channel]
    dao = SmsDao(db)
    created, now = [], utc_now()
    for r in rows:
        if data.text and data.text.strip():
            body = (personalise(data.text, r["customerName"]).replace("{ankara}", r["invoiceNumber"])
                    .replace("{siku}", str(r["days"])).replace("{usd}", f"{r['chargeUsd']:,.2f}")
                    .replace("{tsh}", whole(r["storageCharge"])))
        else:
            body = storage.reminder_text(r["customerName"], r["invoiceNumber"], r["days"], r["storageCharge"],
                                         r["chargeUsd"])
        for ch in channels:
            created.append(dao.create(commit=False, text=body, msisdn=r["phone"],
                                      source=config.SMS_SOURCE_NAME if ch == "SMS" else "WhatsApp",
                                      reference=r["invoiceNumber"], coding=config.SMS_CODING if ch == "SMS" else "UTF8",
                                      smsFor=ESmsStatus.STORAGE_OVERDUE.name, isReceived=False, isSMSSend=False,
                                      channel=ch, invoice_id=r["invoice"].id, logsId=user_id))
        r["debt"].storageRemindedAt = now
    db.flush()
    ids = [s.id for s in created]
    db.commit()
    if data.sendNow:
        dispatch(ids)
    return {"invoices": len(rows), "messages": len(ids), "sending": bool(data.sendNow), "channel": channel}
