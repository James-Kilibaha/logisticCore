"""
Ufuatiliaji wa mzigo kwa umma: mteja anaingiza code ya ofisi (ya mzigo, iko kwenye SMS), track number au
pickup code (ya mpokeaji)
na anaona hatua mzigo ulipo. Hakuna namba za simu wala majina kamili yanayoonyeshwa.
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import config
from ..core.enums import EInvoiceStatus
from ..core.exceptions import NotFound
from ..core.utils import local_now, to_local
from ..invoice.dao import InvoiceDao
from ..package.dao import PackageDao
from ..payment import storage
from ..payment.dao import DebtDao
from ..product.model import Product
from ..receiver.model import Receiver

# Hatua zinazoonyeshwa kwa mteja
STAGES = ["RECEIVED", "SHIPPING", "ARRIVED", "COLLECTED"]
_STAGE = {
    "OPEN": "RECEIVED", "PARKING": "RECEIVED", "PROCESSING": "RECEIVED",
    "SHIPPING": "SHIPPING",
    "STORE": "ARRIVED", "ARRIVE": "ARRIVED", "RECEIVED": "ARRIVED",
    "DELIVERED": "COLLECTED", "COMPLETED": "COLLECTED", "CLOSE": "COLLECTED",
}


def mask(name: str | None) -> str:
    """'Asha Juma' -> 'A*** J***'."""
    parts = [p for p in (name or "").split() if p]
    return " ".join(p[0].upper() + "***" for p in parts) or "-"


def _events(history: str) -> list[dict]:
    seen, out = set(), []
    for raw in (history or "").split(","):
        code, _, when = raw.strip().partition("_")
        stage = _STAGE.get(code)
        if not stage or stage in seen:
            continue
        seen.add(stage)
        try:
            at = datetime.strptime(when[:19], "%Y-%m-%dT%H:%M:%S").isoformat()
        except ValueError:
            at = None
        out.append({"stage": stage, "at": at})
    return out


def track(db: Session, code: str) -> dict:
    code = (code or "").strip()
    if len(code) < 4:
        raise NotFound("Track number not found")
    lowered = code.lower()

    from ..core import office_code

    invoice_id, only_product = None, None
    key = office_code.key(code)
    product = db.query(Product).filter(func.replace(func.upper(Product.officeCode), "-", "") == key).first()
    if product is None:
        product = db.query(Product).filter(func.lower(Product.trackNumber) == lowered).first()
    if product is not None:
        invoice_id, only_product = product.invoice_id, product.id
    else:
        receiver = db.query(Receiver).filter(func.lower(Receiver.trackNumber) == lowered).first()
        if receiver is not None:
            invoice_id = receiver.invoice_id
    invoice = InvoiceDao(db).with_details(invoice_id) if invoice_id else None
    if invoice is None or invoice.status in (EInvoiceStatus.BLOCKED.name, EInvoiceStatus.BLOCK.name):
        raise NotFound("Track number not found")

    products = [p for p in invoice.product if only_product is None or p.id == only_product]
    stage = _STAGE.get(invoice.status, "RECEIVED")
    customer = invoice.customer[0] if invoice.customer else None
    result = {
        "code": code,
        "invoiceNumber": invoice.invoiceNumber,
        "customer": mask(customer.name if customer else None),
        "stage": stage,
        "stages": STAGES,
        "events": _events(invoice.history),
        "items": [{"description": p.description, "trackNumber": p.trackNumber,
                   "carrier": p.carrierType,
                   "quantities": p.quantities, "weight": p.weight} for p in products],
        "box": None,
        "store": None,
        "payment": None,
        "collected": None,
        "company": {"name": config.COMPANY_NAME, "phones": config.COMPANY_PHONES, "origin": config.COMPANY_ORIGIN},
    }

    for package in PackageDao(db).all():
        if any(str(p.id) in (package.productList or "") for p in products):
            result["box"] = {"type": package.packageType, "shipped": bool(package.isBoxClose),
                             "arrived": bool(package.isCollect),
                             "eta": package.eta.isoformat() if package.eta and not package.isCollect else None}
            break

    debt = DebtDao(db).by_invoice(invoice.id)
    if stage == "ARRIVED":
        start = storage.arrival(invoice, debt)
        days = storage.days_in_store(start)
        result["store"] = {
            "arrivedAt": to_local(start).isoformat() if start else None,
            "days": days,
            "freeDays": config.DAYS_TO_CHARGE,
            "freeDaysLeft": max(config.DAYS_TO_CHARGE - days, 0),
            "chargePerDayUsd": config.STORAGE_CHARGE_USD,
        }
    if debt is not None:
        if storage.refresh(db, invoice, debt):
            db.commit()
        result["payment"] = {"status": debt.status, "balance": max(round(debt.debt or 0), 0),
                             "storageCharge": round(debt.storageCharge or 0)}
    if invoice.handover:
        h = invoice.handover[0]
        result["collected"] = {"at": to_local(h.created_at).isoformat() if h.created_at else None,
                               "by": mask(h.collectorName)}
    result["checkedAt"] = local_now().isoformat(timespec="seconds")
    return result
