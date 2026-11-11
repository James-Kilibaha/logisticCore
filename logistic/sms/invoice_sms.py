"""
SMS ya ankara moja: ujumbe unaoorodhesha kila bidhaa ya ankara (maelezo, katoni, kilo/CBM, usafiri, bei),
jumla, kilicholipwa na deni - kwa mteja na/au mpokeaji. Inatumwa kwa mkono kutoka kwenye ukurasa wa ankara.
"""
import logging
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config
from ..core.enums import ESmsStatus
from ..core.exceptions import BadRequest, NotFound
from ..core.phone import try_normalize
from ..core.utils import whole
from ..invoice.dao import InvoiceDao
from . import service
from .broadcast import CHANNELS, dispatch, personalise, segments
from .dao import SmsDao

logger = logging.getLogger(__name__)

_STATUS = {"OPEN": "tumepokea mzigo wako {origin}", "PARKING": "mzigo wako uko tayari kupakiwa {origin}",
           "SHIPPING": "mzigo wako uko safarini kuja Tanzania", "STORE": "mzigo wako umefika ofisini kwetu Tanzania",
           "DELIVERED": "mzigo wako umekabidhiwa", "COMPLETED": "mzigo wako umekabidhiwa"}


class InvoiceSms(BaseModel):
    invoiceId: UUID
    text: str | None = None      # tupu = ujumbe wa bidhaa za ankara (kama kwenye preview)
    toCustomer: bool = True
    toReceiver: bool = False
    channel: str = "SMS"         # SMS / WHATSAPP / BOTH
    sendNow: bool = True


def _load(db: Session, invoice_id):
    invoice = InvoiceDao(db).with_details(invoice_id)
    if invoice is None:
        raise NotFound("Invoice not found")
    if not invoice.product:
        raise BadRequest("Ankara hii haina bidhaa bado")
    return invoice


def _debt(invoice):
    debts = list(invoice.debt or [])
    return debts[0] if debts else None


def message(invoice, name: str | None = None) -> str:
    """Ujumbe wa ankara: hali, bidhaa moja moja, jumla na pesa."""
    from ..payment.service import total_due

    products = sorted(invoice.product, key=lambda p: (p.description or "").lower())
    open_ = (invoice.status or "").upper() not in ("DELIVERED", "COMPLETED")  # bado hajachukua: onyesha code
    status = _STATUS.get((invoice.status or "").upper(), "taarifa za mzigo wako").format(
        origin=config.COMPANY_ORIGIN)
    lines = [f"Habari {name}," if name else "Habari,", f"Ankara #{invoice.invoiceNumber}: {status}.",
             service.items_block(products, with_code=open_), service.totals_line(products)]
    debt = _debt(invoice)
    if debt is not None:
        if debt.storageCharge:
            lines.append(f"Gharama ya stoo (siku {debt.days}): Tsh {whole(debt.storageCharge)}/=")
        if debt.discount:
            lines.append(f"Punguzo: Tsh {whole(debt.discount)}/=")
        balance = debt.debt if debt.debt is not None else total_due(debt) - (debt.paid or 0)
        lines.append(f"Kulipa: Tsh {whole(total_due(debt))}/=, Umelipa: Tsh {whole(debt.paid)}/=, "
                     f"Deni: Tsh {whole(max(balance, 0))}/=")
        if balance > 0:
            lines.append(config.COMPANY_PAYMENT_INFO)
    track = next((service.tracking_code(p) for p in products if service.tracking_code(p)), None)
    link = service.track_link(track).strip()
    if link:
        lines.append(link)
    if open_ and any(p.officeCode for p in products):
        lines.append(service.CODE_NOTE)
    lines.append(f"Tupigie: {config.COMPANY_PHONES}")
    return "\n".join(x for x in lines if x)


def _people(invoice, to_customer: bool, to_receiver: bool) -> list[tuple[str, str, str]]:
    out, seen = [], set()
    customer = invoice.customer[0] if invoice.customer else None
    receiver = invoice.receiver[0] if invoice.receiver else None
    for who, person, wanted in (("CUSTOMER", customer, to_customer), ("RECEIVER", receiver, to_receiver)):
        if not wanted or person is None:
            continue
        phone = try_normalize(person.phoneNumber)
        if phone and phone not in seen:
            seen.add(phone)
            out.append((who, person.name, phone))
    return out


def _person(p) -> dict | None:
    if p is None:
        return None
    return {"name": p.name, "phone": try_normalize(p.phoneNumber)}


def preview(db: Session, invoice_id) -> dict:
    invoice = _load(db, invoice_id)
    customer = invoice.customer[0] if invoice.customer else None
    receiver = invoice.receiver[0] if invoice.receiver else None
    text = message(invoice, customer.name if customer else None)
    return {"invoiceNumber": invoice.invoiceNumber, "items": len(invoice.product), "text": text,
            "segments": segments(text), "customer": _person(customer), "receiver": _person(receiver)}


def send(db: Session, data: InvoiceSms, user_id) -> dict:
    service.ensure_enabled(db, ESmsStatus.INVOICE_SMS)
    invoice = _load(db, data.invoiceId)
    channel = (data.channel or "SMS").upper()
    if channel not in CHANNELS:
        raise BadRequest("channel must be SMS, WHATSAPP or BOTH")
    if channel in ("WHATSAPP", "BOTH") and not config.WHATSAPP_ENABLED:
        raise BadRequest("WhatsApp haijawekwa (WHATSAPP_ENABLED kwenye .env)")
    people = _people(invoice, data.toCustomer, data.toReceiver)
    if not people:
        raise BadRequest("Hakuna namba ya simu kwa uliowachagua")
    custom = (data.text or "").strip()
    if len(custom) > 1600:
        raise BadRequest("Ujumbe ni mrefu sana (herufi 1600 mwisho)")

    dao = SmsDao(db)
    created = []
    for _who, name, phone in people:
        body = personalise(custom, name) if custom else message(invoice, name)
        for ch in (["SMS", "WHATSAPP"] if channel == "BOTH" else [channel]):
            created.append(dao.create(commit=False, text=body, msisdn=phone,
                                      source=config.SMS_SOURCE_NAME if ch == "SMS" else "WhatsApp",
                                      reference=invoice.invoiceNumber,
                                      coding=config.SMS_CODING if ch == "SMS" else "UTF8",
                                      smsFor=ESmsStatus.INVOICE_SMS.name, isReceived=False, isSMSSend=False, channel=ch,
                                      invoice_id=invoice.id, logsId=user_id))
    db.flush()
    ids = [s.id for s in created]
    db.commit()
    if data.sendNow:
        dispatch(ids)
    logger.info("SMS ya ankara %s: watu %s, ujumbe %s (%s)", invoice.invoiceNumber, len(people), len(ids), channel)
    return {"recipients": len(people), "messages": len(ids), "sending": bool(data.sendNow), "channel": channel,
            "to": [{"who": w, "name": n, "phone": p} for w, n, p in people]}
