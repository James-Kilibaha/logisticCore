"""
Madai ya mzigo ulioharibika (DAMAGED), kupotea (LOST) au katoni pungufu (SHORT).

Mtiririko: OPEN -> APPROVED (na fidia) au REJECTED.
Fidia ikiidhinishwa:
  - DISCOUNT: inaongezwa kwenye punguzo la ankara (deni linapungua)
  - REFUND  : pesa inarudishwa kwa mteja (malipo ya aina REFUND kwenye ankara)
  - NONE    : imeidhinishwa bila pesa (mf. mzigo umepatikana)
"""
import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..core import files
from ..core.audit import note
from ..core.base_model import utc_now
from ..core.dao import to_uuid
from ..core.enums import EPaymentKind
from ..core.exceptions import BadRequest, NotFound
from ..core.utils import whole
from ..invoice.dao import InvoiceDao
from ..payment import service as payment_service
from ..payment.dao import DebtDao, PaymentDao
from ..product.model import Product
from ..settings.institute.dao import InstituteDao
from ..user.dao import UserDao
from . import schema
from .model import CargoClaim



def parse(raw: str) -> schema.Create:
    try:
        return schema.Create(**json.loads(raw))
    except json.JSONDecodeError:
        raise BadRequest("stringValue must be valid JSON")
    except ValidationError as error:
        raise BadRequest("; ".join(e["msg"].replace("Value error, ", "") for e in error.errors()))


def _get(db: Session, claim_id) -> CargoClaim:
    claim = db.query(CargoClaim).filter(CargoClaim.id == to_uuid(claim_id)).one_or_none()
    if claim is None:
        raise NotFound("Claim not found")
    return claim


def display(db: Session, claims: list[CargoClaim]) -> list[schema.Display]:
    from ..invoice.model import Invoice
    from ..user.model import User

    inv_ids = {c.invoice_id for c in claims}
    prod_ids = {c.product_id for c in claims if c.product_id}
    user_ids = {c.logsId for c in claims} | {c.resolvedBy for c in claims if c.resolvedBy}
    invoices = {i.id: i for i in db.query(Invoice).filter(Invoice.id.in_(inv_ids)).all()} if inv_ids else {}
    products = dict(db.query(Product.id, Product.description).filter(Product.id.in_(prod_ids)).all()) if prod_ids else {}
    users = {u.id: f"{u.firstName} {u.lastName}" for u in db.query(User).filter(User.id.in_(user_ids)).all()} \
        if user_ids else {}
    out = []
    for c in claims:
        d = schema.Display.model_validate(c)
        inv = invoices.get(c.invoice_id)
        d.hasPhoto = bool(c.photoPath)
        d.invoiceNumber = inv.invoiceNumber if inv else None
        d.customerName = inv.customer[0].name if inv and inv.customer else None
        d.productName = products.get(c.product_id)
        d.reportedBy = users.get(c.logsId)
        d.resolvedByName = users.get(c.resolvedBy)
        out.append(d)
    return out


def create(db: Session, data: schema.Create, photo: tuple[str, bytes] | None, user_id) -> schema.Display:
    invoice = InvoiceDao(db).with_details(data.invoiceId)
    if invoice is None:
        raise NotFound("The Invoice does not exist")
    product = None
    if data.productId:
        product = next((p for p in invoice.product if p.id == data.productId), None)
        if product is None:
            raise BadRequest("Product is not in this invoice")
        if data.cartons and data.cartons > (product.quantities or 1):
            raise BadRequest(f"The product only has {product.quantities:g} cartons")
    path = files.save_image(photo[0], photo[1], files.CLAIMS_DIR) if photo else None
    try:
        claim = CargoClaim(invoice_id=invoice.id, product_id=product.id if product else None, type=data.type,
                           cartons=data.cartons, description=data.description.strip(), photoPath=path,
                           status="OPEN", compensation=0.0, settlement="NONE", logsId=user_id)
        db.add(claim)
        from ..notification.service import notify

        notify(db, "PAYMENT", "update", kind="CLAIM", exclude=user_id,
               title=f"Dai jipya: ankara {invoice.invoiceNumber}",
               body=data.description.strip()[:200], link=f"invoice:{invoice.id}")
        db.commit()
    except Exception:
        db.rollback()
        files.remove(path)
        raise
    note(f"Dai jipya ({data.type}) ankara {invoice.invoiceNumber}: {data.description.strip()[:120]}")
    return display(db, [claim])[0]


def search(db: Session, f: schema.Filter) -> list[schema.Display]:
    q = db.query(CargoClaim)
    if f.status:
        q = q.filter(CargoClaim.status == f.status.upper())
    if f.invoiceId:
        q = q.filter(CargoClaim.invoice_id == f.invoiceId)
    claims = q.order_by(CargoClaim.created_at.desc()).offset(f.offset).limit(f.limit).all()
    return display(db, claims)


def resolve(db: Session, claim_id, data: schema.Resolve, user_id) -> schema.Display:
    claim = _get(db, claim_id)
    if claim.status != "OPEN":
        raise BadRequest("This claim has already been resolved")
    invoice = InvoiceDao(db).get(claim.invoice_id)
    compensation = data.compensation if data.status == "APPROVED" else 0.0
    settlement = data.settlement if compensation > 0 else "NONE"

    if settlement in ("DISCOUNT", "REFUND"):
        debt = DebtDao(db).by_invoice(claim.invoice_id)
        if debt is None:
            raise BadRequest("Create the invoice (bill) first so the compensation can be recorded")
        if settlement == "DISCOUNT":
            gross = (debt.amount or 0) + (debt.storageCharge or 0)
            new_discount = (debt.discount or 0) + compensation
            if new_discount > gross + 1:
                raise BadRequest(f"Compensation is more than the invoice total ({whole(gross)}). Use REFUND")
            debt.discount = new_discount
            reason = f"Fidia ya dai ({claim.type})"
            debt.discountNote = f"{debt.discountNote}; {reason}" if debt.discountNote else reason
        else:
            if data.instituteId is None or InstituteDao(db).get(data.instituteId) is None:
                raise BadRequest("Choose how the money is paid back (instituteId)")
            PaymentDao(db).create(commit=False, paid=compensation, kind=EPaymentKind.REFUND.name, currency="TZS",
                                  note=f"Fidia ya dai: {data.resolution.strip()[:80]}",
                                  receiptNumber=payment_service._next_receipt(db), debt_id=debt.id,
                                  institute_id=data.instituteId, logsId=user_id)
        payment_service.recalculate(db, debt)

    claim.status = "SETTLED" if settlement != "NONE" else data.status
    claim.compensation = compensation
    claim.settlement = settlement
    claim.resolution = data.resolution.strip()
    claim.resolvedBy = user_id
    claim.resolvedAt = utc_now()
    db.commit()
    note(f"Dai ankara {invoice.invoiceNumber if invoice else '-'}: {claim.status}"
         + (f", fidia TSh {whole(compensation)} ({settlement})" if compensation else ""))
    return display(db, [claim])[0]


def photo_path(db: Session, claim_id):
    claim = _get(db, claim_id)
    if not claim.photoPath:
        raise NotFound("File not found")
    return files.existing(claim.photoPath)


def counts(db: Session) -> dict:
    from sqlalchemy import func

    return dict(db.query(CargoClaim.status, func.count(CargoClaim.id)).group_by(CargoClaim.status).all())
