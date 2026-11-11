"""
Makadirio ya bei (quotation): mteja anauliza "mzigo huu utagharimu kiasi gani?" kabla haujapokelewa.

- Bei inahesabiwa kwa bei za Mipangilio: ndege = kwa kilo, meli = kwa CBM (au kilo kama hakuna bei ya CBM).
- Inatumwa kwa SMS / WhatsApp na PDF; ikikubaliwa inageuzwa kuwa ankara (mteja anasajiliwa kama hayupo).
"""
from datetime import date
from types import SimpleNamespace

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .. import config
from ..core.base_model import utc_now
from ..core.exceptions import BadRequest, NotFound
from ..core.phone import try_normalize
from ..core.utils import title, whole
from ..settings.price.model import Price
from . import schema
from .model import Quotation, QuotationItem

STATUSES = ("DRAFT", "SENT", "ACCEPTED", "REJECTED", "CONVERTED")
_CARRIER = {"AIR": "Ndege", "SEA": "Meli"}


# ------------------------------------------------------------------ bei
def _fx(price: Price) -> float:
    """Kiwango cha kubadilisha sarafu ya bei kuwa TSh (sarafu iliyo hai), kama ilivyo kwenye app."""
    active = None
    for c in list(price.currency or []):
        if active is None or not c.isBlocked:
            active = c
    return float(active.buy) if active is not None and active.buy else 1.0


def _default_price(db: Session, carrier: str) -> Price | None:
    prices = db.query(Price).filter(Price.isBlocked.is_(False)).order_by(Price.created_at.desc()).all()
    kg = [p for p in prices if (p.unit or "KG").upper() != "CBM"]
    if carrier == "SEA":
        cbm = [p for p in prices if (p.unit or "KG").upper() == "CBM"]
        return (cbm or kg or [None])[0]
    return (kg or [None])[0]


def _item_cbm(item: schema.Item) -> float:
    if item.cbm is not None and item.cbm > 0:
        return float(item.cbm)
    if item.length and item.width and item.height:
        return item.length * item.width * item.height / 1_000_000 * max(item.quantities or 1, 1)
    return 0.0


def compute(db: Session, items: list[schema.Item]) -> list[dict]:
    rows = []
    for i, item in enumerate(items):
        price = db.get(Price, item.priceId) if item.priceId else _default_price(db, item.carrierType)
        if item.priceId and price is None:
            raise NotFound("Price not found")
        unit = ((price.unit if price else None) or "KG").upper()
        cbm = _item_cbm(item)
        rate = (price.cost / (price.weight or 1) * _fx(price)) if price else 0.0
        qty = cbm if unit == "CBM" else (item.weight or 0)
        amount = item.amount if item.amount is not None else round(qty * rate)
        rows.append({"position": i, "description": title(item.description.strip()), "carrierType": item.carrierType,
                     "quantities": item.quantities or 0, "weight": item.weight or 0, "cbm": round(cbm, 4),
                     "length": item.length, "width": item.width, "height": item.height,
                     "price_id": price.id if price else None, "unit": unit, "rate": round(rate, 2),
                     "amount": float(amount)})
    return rows


def calculate(db: Session, data: schema.Calculate) -> dict:
    rows = compute(db, data.items)
    return {"items": [{**r, "price_id": str(r["price_id"]) if r["price_id"] else None} for r in rows],
            "total": sum(r["amount"] for r in rows)}


# --------------------------------------------------------------- kuonyesha
def _expired(q: Quotation) -> bool:
    return q.status in ("DRAFT", "SENT") and q.validUntil is not None and q.validUntil < date.today()


def display(q: Quotation, invoice_number: str | None = None) -> dict:
    items = [{"id": str(i.id), "description": i.description, "carrierType": i.carrierType, "quantities": i.quantities,
              "weight": i.weight, "cbm": i.cbm, "length": i.length, "width": i.width, "height": i.height,
              "priceId": str(i.price_id) if i.price_id else None, "unit": i.unit, "rate": i.rate, "amount": i.amount}
             for i in q.items]
    return {"id": str(q.id), "number": q.number, "status": q.status, "expired": _expired(q),
            "customerId": str(q.customer_id) if q.customer_id else None, "customerName": q.customerName,
            "phoneNumber": q.phoneNumber, "validUntil": q.validUntil.isoformat() if q.validUntil else None,
            "note": q.note, "total": q.total, "invoiceId": str(q.invoice_id) if q.invoice_id else None,
            "invoiceNumber": invoice_number, "items": items,
            "kg": sum(i.weight or 0 for i in q.items if i.carrierType != "SEA"),
            "cbm": sum(i.cbm or 0 for i in q.items if i.carrierType == "SEA"),
            "cartons": sum(i.quantities or 0 for i in q.items),
            "created_at": q.created_at.isoformat() if q.created_at else None}


def _invoice_number(db: Session, q: Quotation) -> str | None:
    if not q.invoice_id:
        return None
    from ..invoice.model import Invoice

    inv = db.get(Invoice, q.invoice_id)
    return inv.invoiceNumber if inv else None


def _get(db: Session, quotation_id) -> Quotation:
    from ..core.dao import to_uuid

    q = (db.query(Quotation).options(selectinload(Quotation.items))
         .filter(Quotation.id == to_uuid(quotation_id)).one_or_none())
    if q is None:
        raise NotFound("Quotation not found")
    return q


def get(db: Session, quotation_id) -> dict:
    q = _get(db, quotation_id)
    return display(q, _invoice_number(db, q))


# ------------------------------------------------------------- kuhifadhi
def _next_number(db: Session) -> str:
    prefix = f"Q{utc_now():%y%m}-"
    n = db.query(func.count(Quotation.id)).filter(Quotation.number.like(f"{prefix}%")).scalar() or 0
    return f"{prefix}{n + 1:04d}"


def _fill(db: Session, q: Quotation, data: schema.Save, user_id) -> None:
    from ..customer.model import Customer

    if not data.items:
        raise BadRequest("Ongeza angalau bidhaa moja")
    customer = db.get(Customer, data.customerId) if data.customerId else None
    if data.customerId and customer is None:
        raise NotFound("The Customer does not exist")
    name = (data.customerName or (customer.name if customer else "") or "").strip()
    if not name:
        raise BadRequest("Andika jina la mteja")
    phone = try_normalize(data.phoneNumber) if data.phoneNumber else (try_normalize(customer.phoneNumber) if customer else None)
    if data.phoneNumber and not phone:
        raise BadRequest("Namba ya simu si sahihi")
    rows = compute(db, data.items)
    q.customer_id = customer.id if customer else None
    q.customerName = title(name)
    q.phoneNumber = phone
    q.validUntil = schema.valid_until(data.validDays)
    q.note = (data.note or "").strip()[:500] or None
    q.total = sum(r["amount"] for r in rows)
    q.items.clear()
    db.flush()
    for r in rows:
        q.items.append(QuotationItem(logsId=user_id, **r))


def create(db: Session, data: schema.Save, user_id) -> dict:
    from ..core.scope import office_scope, user_office

    for _ in range(3):
        q = Quotation(number=_next_number(db), status="DRAFT", logsId=user_id, customerName="-", total=0,
                      office_id=office_scope(db, user_id) or user_office(db, user_id))
        db.add(q)
        try:
            _fill(db, q, data, user_id)
            db.commit()
            return get(db, q.id)
        except IntegrityError:  # namba imechukuliwa na mtumiaji mwingine kwa wakati huo huo
            db.rollback()
    raise BadRequest("Could not create quotation number, try again")


def update(db: Session, quotation_id, data: schema.Save, user_id) -> dict:
    q = _get(db, quotation_id)
    if q.status == "CONVERTED":
        raise BadRequest("Makadirio yaliyogeuzwa kuwa ankara hayabadilishwi")
    _fill(db, q, data, user_id)
    db.commit()
    return get(db, q.id)


def set_status(db: Session, quotation_id, status: str) -> dict:
    status = (status or "").upper()
    if status not in STATUSES or status == "CONVERTED":
        raise BadRequest("status must be DRAFT, SENT, ACCEPTED or REJECTED")
    q = _get(db, quotation_id)
    if q.status == "CONVERTED":
        raise BadRequest("Makadirio haya yameshageuzwa kuwa ankara")
    q.status = status
    db.commit()
    return get(db, q.id)


def delete(db: Session, quotation_id) -> bool:
    q = _get(db, quotation_id)
    if q.status == "CONVERTED":
        raise BadRequest("Makadirio yaliyogeuzwa kuwa ankara hayafutwi")
    db.delete(q)
    db.commit()
    return True


def search(db: Session, f: schema.Search, user_id) -> dict:
    from ..core.scope import office_scope

    qry = db.query(Quotation)
    office = office_scope(db, user_id)
    if office is not None:
        qry = qry.filter(or_(Quotation.office_id == office, Quotation.office_id.is_(None)))
    counts = dict(qry.with_entities(Quotation.status, func.count(Quotation.id)).group_by(Quotation.status).all())
    if f.status:
        qry = qry.filter(Quotation.status == f.status.upper())
    if f.customerId:
        qry = qry.filter(Quotation.customer_id == f.customerId)
    if f.q:
        like = f"%{f.q.strip()}%"
        digits = "".join(c for c in f.q if c.isdigit())
        conds = [Quotation.number.ilike(like), Quotation.customerName.ilike(like)]
        if len(digits) >= 4:
            conds.append(Quotation.phoneNumber.like(f"%{digits[-9:]}%"))
        qry = qry.filter(or_(*conds))
    total = qry.count()
    rows = (qry.options(selectinload(Quotation.items)).order_by(Quotation.created_at.desc())
            .offset(f.offset).limit(f.limit).all())
    return {"total": total, "counts": counts, "items": [display(q) for q in rows]}


# ------------------------------------------------------------ SMS na PDF
def _as_lines(q: Quotation):
    return [SimpleNamespace(description=i.description, quantities=i.quantities, weight=i.weight, unitPrice=i.amount,
                            carrierType=i.carrierType, trackNumber=None, cbm=i.cbm, length=i.length, width=i.width,
                            height=i.height, price=[]) for i in q.items]


def message(q: Quotation, name: str | None = None) -> str:
    from ..sms import service as sms_service

    lines = _as_lines(q)
    valid = f" (halali hadi {q.validUntil:%d/%m/%Y})" if q.validUntil else ""
    parts = [f"Habari {name or q.customerName},", f"Makadirio ya bei #{q.number}{valid}:",
             sms_service.items_block(lines), sms_service.totals_line(lines)]
    if q.note:
        parts.append(q.note)
    parts.append("Bei halisi itahesabiwa mzigo ukipimwa ofisini kwetu.")
    parts.append(f"Tupigie: {config.COMPANY_PHONES}")
    return "\n".join(p for p in parts if p)


def send_sms(db: Session, quotation_id, data: schema.SendSms, user_id) -> dict:
    from ..core.enums import ESmsStatus
    from ..sms.broadcast import CHANNELS, dispatch
    from ..sms.dao import SmsDao
    from ..sms.service import ensure_enabled

    ensure_enabled(db, ESmsStatus.QUOTATION)
    q = _get(db, quotation_id)
    if not q.phoneNumber:
        raise BadRequest("Makadirio haya hayana namba ya simu")
    channel = (data.channel or "SMS").upper()
    if channel not in CHANNELS:
        raise BadRequest("channel must be SMS, WHATSAPP or BOTH")
    if channel in ("WHATSAPP", "BOTH") and not config.WHATSAPP_ENABLED:
        raise BadRequest("WhatsApp haijawekwa (WHATSAPP_ENABLED kwenye .env)")
    text = (data.text or "").strip() or message(q)
    dao = SmsDao(db)
    created = [dao.create(commit=False, text=text, msisdn=q.phoneNumber,
                          source=config.SMS_SOURCE_NAME if ch == "SMS" else "WhatsApp", reference=q.number,
                          coding=config.SMS_CODING if ch == "SMS" else "UTF8", smsFor=ESmsStatus.QUOTATION.name,
                          isReceived=False, isSMSSend=False, channel=ch, invoice_id=None, logsId=user_id)
               for ch in (["SMS", "WHATSAPP"] if channel == "BOTH" else [channel])]
    if q.status == "DRAFT":
        q.status = "SENT"
    db.flush()
    ids = [s.id for s in created]
    db.commit()
    dispatch(ids)
    return {"messages": len(ids), "channel": channel, "status": q.status}


def pdf(db: Session, quotation_id) -> tuple[bytes, str]:
    from ..core.report_pdf import ReportPdf, money, num

    q = _get(db, quotation_id)
    doc = ReportPdf("Makadirio ya bei", subtitle=f"#{q.number}",
                    period=f"Halali hadi {q.validUntil:%d/%m/%Y}" if q.validUntil else None)
    doc.kpis([("Mteja", q.customerName), ("Simu", q.phoneNumber or "-"),
              ("Tarehe", f"{q.created_at:%d/%m/%Y}" if q.created_at else "-"), ("Jumla (TSh)", money(q.total))])
    rows = []
    for n, i in enumerate(q.items, 1):
        sea = i.carrierType == "SEA"
        measure = f"{num(i.cbm)} CBM" if (i.unit == "CBM") else f"{num(i.weight)} kg"
        rows.append([str(n), i.description, _CARRIER.get(i.carrierType, i.carrierType), i.quantities,
                     0 if sea else i.weight, i.cbm if sea else 0, (i.weight or 0) / 1000 if sea else 0,
                     f"{measure} x {whole(i.rate)}", i.amount])
    doc.table(["#", "Bidhaa", "Usafiri", "Katoni", "Kg (ndege)", "CBM (meli)", "Tani (meli)", "Hesabu", "Kiasi (TSh)"],
              rows, widths=[0.5, 3, 1.1, 1, 1.2, 1.2, 1.2, 2.4, 1.8], numbers={3, 4, 5, 6}, money={8},
              totals={3, 4, 5, 6, 8})
    if q.note:
        doc.section("Maelezo")
        doc.note(q.note)
    doc.section("Masharti")
    doc.note("Haya ni makadirio. Kiasi halisi kitahesabiwa kwa uzito/ujazo halisi mzigo ukipimwa ofisini kwetu, "
             "kwa bei zilizopo siku hiyo.")
    doc.note(f"Mzigo ukifika Tanzania unakaa siku {config.DAYS_TO_CHARGE} bure; baada ya hapo Dola "
             f"{config.STORAGE_CHARGE_USD:,.2f} kwa kila siku.")
    return doc.build(), f"makadirio_{q.number}"


# ------------------------------------------------------- kugeuza kuwa ankara
def convert(db: Session, quotation_id, data: schema.Convert, user_id) -> dict:
    from ..core.permission import Action, Module, need
    from ..customer import schema as customer_schema
    from ..customer import service as customer_service
    from ..customer.dao import CustomerDao
    from ..invoice import schema as invoice_schema
    from ..invoice import service as invoice_service
    from ..product.dao import ProductDao

    q = _get(db, quotation_id)
    if q.status == "CONVERTED":
        raise BadRequest("Makadirio haya yameshageuzwa kuwa ankara")
    if q.status == "REJECTED":
        raise BadRequest("Makadirio yaliyokataliwa hayageuzwi - yabadilishe kwanza")
    customer = CustomerDao(db).get(q.customer_id) if q.customer_id else None
    if customer is None and q.phoneNumber:
        customer = CustomerDao(db).by_phone(q.phoneNumber)
    if customer is None:
        need(db, user_id, Module.CUSTOMER, Action.INSERT)
        customer = customer_service.create(db, customer_schema.Insert(name=q.customerName, phoneNumber=q.phoneNumber),
                                           user_id)
    invoice = invoice_service.create(db, invoice_schema.Create(customer_id=customer.id, office_id=data.officeId), user_id)
    dao = ProductDao(db)
    for i in q.items:
        length, width, height = i.length, i.width, i.height
        if i.carrierType == "SEA" and i.cbm and not (length and width and height):
            # CBM iliyoandikwa moja kwa moja -> vipimo sawa navyo (100 x 100 x h cm kwa katoni)
            length, width, height = 100.0, 100.0, i.cbm / max(i.quantities or 1, 1) * 100
        dao.create(commit=False, description=i.description, unitPrice=i.amount, quantities=i.quantities or 0,
                   weight=i.weight or 0, trackNumber=None, carrierType=i.carrierType, length=length, width=width,
                   height=height, price_id=i.price_id, invoice_id=invoice.id, path=None, logsId=user_id)
    q.status = "CONVERTED"
    q.invoice_id = invoice.id
    q.customer_id = customer.id
    db.commit()
    return {"invoiceId": str(invoice.id), "invoiceNumber": invoice.invoiceNumber, "customerId": str(customer.id),
            "quotation": get(db, q.id)}
