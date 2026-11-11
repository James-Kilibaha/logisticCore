"""
Orodha ya makabidhiano yote (mizigo iliyokabidhiwa) yenye kutafuta na kuchuja:
tarehe, mteja, aliyekabidhi (mfanyakazi), mchukuaji, jina la mzigo / track, usafiri (AIR / SEA), mkopo.
"""
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_
from sqlalchemy.orm import Session

from ..core.phone import search_digits
from ..core.utils import day_range, to_local
from ..customer.model import Customer
from ..invoice.model import Invoice
from ..product.model import Product
from ..user.model import User
from .model import Handover, HandoverItem


class Filter(BaseModel):
    startDate: str | None = None   # YYYY-MM-DD (saa za hapa)
    endDate: str | None = None
    q: str | None = None           # ankara, mteja, simu, mchukuaji, mfanyakazi, mzigo, track
    customerId: UUID | None = None
    staffId: UUID | None = None    # aliyekabidhi
    carrier: str | None = None     # AIR / SEA
    onCredit: bool | None = None
    offset: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=5000)


def _query(db: Session, f: Filter, office=None):
    q = (db.query(Handover, Invoice, Customer, User)
         .join(Invoice, Invoice.id == Handover.invoice_id)
         .outerjoin(Customer, Customer.id == Invoice.customer_id)
         .outerjoin(User, User.id == Handover.logsId))
    start, end = day_range(f.startDate, f.endDate)
    if start is not None:
        q = q.filter(Handover.created_at >= start)
    if end is not None:
        q = q.filter(Handover.created_at < end)
    if office is not None:
        q = q.filter(or_(Invoice.office_id == office, Invoice.office_id.is_(None)))
    if f.customerId:
        q = q.filter(Invoice.customer_id == f.customerId)
    if f.staffId:
        q = q.filter(Handover.logsId == f.staffId)
    if f.onCredit is not None:
        q = q.filter(Handover.onCredit.is_(f.onCredit))
    if f.carrier and f.carrier.strip():
        carrier = f.carrier.strip().upper()
        with_items = exists().where(HandoverItem.handover_id == Handover.id, Product.id == HandoverItem.product_id,
                                    Product.carrierType == carrier)
        no_items = (~exists().where(HandoverItem.handover_id == Handover.id)) & exists().where(
            Product.invoice_id == Handover.invoice_id, Product.carrierType == carrier)
        q = q.filter(or_(with_items, no_items))
    text = (f.q or "").strip()
    if text:
        like = f"%{text}%"
        digits = search_digits(text)
        plike = f"%{digits}%" if len(digits) >= 6 else like
        q = q.filter(or_(
            Invoice.invoiceNumber.ilike(like),
            Customer.name.ilike(like), Customer.phoneNumber.ilike(plike),
            Handover.collectorName.ilike(like), Handover.collectorPhone.ilike(plike),
            User.firstName.ilike(like), User.lastName.ilike(like), User.username.ilike(like),
            (User.firstName + " " + User.lastName).ilike(like),
            exists().where(Product.invoice_id == Handover.invoice_id,
                           or_(Product.description.ilike(like), Product.trackNumber.ilike(like))),
        ))
    return q


def _items(db: Session, rows) -> dict:
    """Bidhaa za kila makabidhiano: kutoka items, au (makabidhiano ya zamani bila items) bidhaa zote za ankara."""
    if not rows:
        return {}
    handover_ids = [h.id for h, *_ in rows]
    invoice_ids = list({h.invoice_id for h, *_ in rows})
    products = {p.id: p for p in db.query(Product).filter(Product.invoice_id.in_(invoice_ids)).all()}
    by_handover: dict = {}
    for it in db.query(HandoverItem).filter(HandoverItem.handover_id.in_(handover_ids)).all():
        p = products.get(it.product_id)
        if p is not None:
            by_handover.setdefault(it.handover_id, []).append((p, it.cartons))
    out = {}
    for h, *_ in rows:
        pairs = by_handover.get(h.id)
        if pairs is None:
            pairs = [(p, p.quantities or 0) for p in products.values() if p.invoice_id == h.invoice_id]
        out[h.id] = [{"productId": str(p.id), "description": p.description, "trackNumber": p.trackNumber,
                      "carrierType": p.carrierType, "cartons": c} for p, c in pairs]
    return out


def search(db: Session, f: Filter, office=None) -> dict:
    q = _query(db, f, office)
    total = q.count()
    rows = q.order_by(Handover.created_at.desc()).offset(f.offset).limit(f.limit).all()
    items = _items(db, rows)
    out = []
    for h, inv, c, u in rows:
        its = items.get(h.id, [])
        carriers = sorted({i["carrierType"] for i in its if i["carrierType"]})
        out.append({
            "id": str(h.id), "invoiceId": str(inv.id), "invoiceNumber": inv.invoiceNumber, "invoiceStatus": inv.status,
            "customerId": str(c.id) if c else None, "customerName": c.name if c else "-",
            "customerPhone": c.phoneNumber if c else None,
            "collectorName": h.collectorName, "collectorPhone": h.collectorPhone, "isReceiver": h.isReceiver,
            "idType": h.idType, "idNumber": h.idNumber,
            "staffId": str(h.logsId) if h.logsId else None,
            "staffName": f"{u.firstName} {u.lastName}" if u else None,
            "onCredit": bool(h.onCredit), "balance": h.balance or 0,
            "cartons": sum(i["cartons"] or 0 for i in its), "carriers": carriers, "items": its,
            "hasSignature": bool(h.signaturePath), "created_at": h.created_at.isoformat() if h.created_at else None,
        })
    staff = (db.query(User.id, User.firstName, User.lastName)
             .filter(User.id.in_(db.query(Handover.logsId).distinct())).order_by(User.firstName).all())
    return {"total": total, "offset": f.offset, "items": out,
            "staff": [{"id": str(i), "name": f"{a} {b}"} for i, a, b in staff]}


def export(db: Session, f: Filter, office=None) -> tuple[bytes, str]:
    from ..core import excel
    from ..core.utils import local_now

    f = f.model_copy(update={"offset": 0, "limit": 5000})
    data = search(db, f, office)
    rows = []
    for r in data["items"]:
        when = to_local(_parse(r["created_at"]))
        rows.append([when, r["invoiceNumber"], r["customerName"], r["customerPhone"] or "",
                     "; ".join(f"{i['description']} ({i['cartons']:g})" for i in r["items"]),
                     ", ".join("Ndege" if c == "AIR" else "Meli" if c == "SEA" else c for c in r["carriers"]),
                     r["cartons"], r["collectorName"], r["collectorPhone"] or "", r["staffName"] or "",
                     "Ndiyo" if r["onCredit"] else "Hapana", r["balance"]])
    label = f"Kipindi: {f.startDate or 'mwanzo'} hadi {f.endDate or 'leo'}"
    sheet = excel.Sheet("Mizigo iliyokabidhiwa", ["Tarehe", "Ankara", "Mteja", "Simu", "Mizigo", "Usafiri", "Katoni",
                                                  "Mchukuaji", "Simu ya mchukuaji", "Aliyekabidhi", "Mkopo",
                                                  "Deni wakati huo"], rows,
                        money={11}, totals={6, 11}, subtitle=label)
    return excel.build([sheet]), f"mizigo_iliyokabidhiwa_{local_now():%Y%m%d}"


def _parse(value: str | None):
    from datetime import datetime

    return datetime.fromisoformat(value) if value else None
