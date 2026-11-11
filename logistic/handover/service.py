"""
Kukabidhi mzigo uliofika stoo.

Sheria:
- Invoice lazima iwe STORE na iwe na ankara (deni) - yaani PDF imeshatengenezwa.
- Deni (pamoja na gharama za stoo) lazima liwe limelipwa, isipokuwa `onCredit=true`
  na mtumiaji ana ruhusa ya PAYMENT/update.
- Baada ya kukabidhi: invoice -> COMPLETED (imelipwa) au DELIVERED (bado inadaiwa).
"""
import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from .. import config
from ..core import files, pdf
from ..core.audit import note
from ..core.enums import Action, EInvoiceStatus, EPaymentStatus, ESmsStatus, Module
from ..core.exceptions import BadRequest, Conflict, NotFound, PermissionDenied
from ..core.utils import stamp, whole
from ..invoice.dao import InvoiceDao
from ..payment import service as payment_service
from ..payment import storage
from ..payment.dao import DebtDao
from ..permission.dao import PermissionDao
from ..user.dao import UserDao
from . import schema
from .dao import HandoverDao
from .model import Handover, HandoverItem


def parse(raw: str) -> schema.Create:
    try:
        return schema.Create(**json.loads(raw))
    except json.JSONDecodeError:
        raise BadRequest("stringValue must be valid JSON")
    except ValidationError as error:
        raise BadRequest("; ".join(e["msg"].replace("Value error, ", "") for e in error.errors()))


def _collected(invoice) -> dict:
    """Katoni zilizokwisha kuchukuliwa kwa kila bidhaa."""
    done: dict = {}
    for h in invoice.handover or []:
        if not h.items:  # makabidhiano ya zamani (bila items) = mzigo wote
            return {p.id: (p.quantities or 1) for p in invoice.product}
        for item in h.items:
            done[item.product_id] = done.get(item.product_id, 0) + (item.cartons or 0)
    return done


def remaining(invoice) -> list[schema.Remaining]:
    done = _collected(invoice)
    rows = []
    for p in invoice.product:
        total = p.quantities or 1
        got = min(done.get(p.id, 0), total)
        rows.append(schema.Remaining(productId=p.id, description=p.description, trackNumber=p.trackNumber,
                                     cartons=total, collected=got, remaining=max(total - got, 0),
                                     needsCode=bool(p.officeCode)))
    return rows


def _check_codes(db: Session, invoice, wanted: dict, data: schema.Create, user_id) -> bool:
    """
    Kila mzigo unaochukuliwa wenye code ya ofisi: mchukuaji lazima aonyeshe code yake (SMS / lebo).
    Msimamizi (HANDOVER update) anaweza kuruhusu bila code (mf. mteja ameipoteza). Code isiyo ya mzigo
    wowote wa ankara hii inakataliwa. Inarudisha True kama code zote zilihakikiwa.
    """
    from ..core import office_code

    taking = [p for p in invoice.product if wanted.get(p.id, 0) > 0 and p.officeCode]
    if not taking:
        return False
    given = office_code.split(data.officeCodes) | office_code.split(data.officeCode)
    mine = {office_code.key(p.officeCode) for p in invoice.product if p.officeCode}
    wrong = given - mine
    if wrong:
        raise BadRequest(f"Code si sahihi kwa ankara hii: {', '.join(sorted(wrong))}")
    missing = [p.description for p in taking if office_code.key(p.officeCode) not in given]
    if not missing:
        return True
    if PermissionDao(db).has(user_id, Module.HANDOVER.value, Action.UPDATE.value):
        return False
    raise BadRequest(f"Weka code ya ofisi ya: {', '.join(missing)} (mpokeaji aliitumiwa kwa SMS / iko kwenye lebo)")


def create(db: Session, data: schema.Create, signature: tuple[str, bytes] | None, photo: tuple[str, bytes] | None,
           current_user_id) -> schema.Display:
    from ..core import phone as phones

    collector_phone = phones.normalize(data.collectorPhone, label="Simu ya mchukuaji")
    invoice_dao = InvoiceDao(db)
    invoice = invoice_dao.with_details(data.invoiceId)
    if invoice is None:
        raise NotFound("The Invoice does not exist")
    if invoice.status != EInvoiceStatus.STORE.name:
        if invoice.handover:
            raise Conflict("This cargo has already been handed over")
        raise BadRequest("Only cargo that is in the store can be handed over")
    debt = DebtDao(db).by_invoice(invoice.id)
    if debt is None:
        raise BadRequest("Create the invoice (bill) first")


    left = {r.productId: r for r in remaining(invoice)}
    if not any(r.remaining > 0 for r in left.values()):
        raise Conflict("This cargo has already been handed over")
    if data.items:
        wanted: dict = {}
        for item in data.items:
            row = left.get(item.productId)
            if row is None:
                raise BadRequest("Product is not in this invoice")
            wanted[item.productId] = wanted.get(item.productId, 0) + item.cartons
            if wanted[item.productId] > row.remaining + 1e-9:
                raise BadRequest(f"Only {row.remaining:g} cartons of '{row.description}' remain")
    else:
        wanted = {pid: r.remaining for pid, r in left.items() if r.remaining > 0}
    final = all(abs(wanted.get(pid, 0) - r.remaining) < 1e-9 for pid, r in left.items() if r.remaining > 0)
    code_verified = _check_codes(db, invoice, wanted, data, current_user_id)

    storage.refresh(db, invoice, debt)
    payment_service.recalculate(db, debt)
    balance = max(debt.debt or 0, 0)
    owing = debt.status != EPaymentStatus.PAID.name
    if owing and not data.onCredit:
        raise BadRequest(f"Balance remaining: TSh {whole(balance)}. Receive payment first")
    if owing and not PermissionDao(db).has(current_user_id, Module.HANDOVER.value, Action.UPDATE.value):
        raise PermissionDenied("You do not have permission to hand over cargo on credit")
    if owing:
        from ..payment import credit

        credit.check(db, invoice.customer[0] if invoice.customer else None, invoice, balance)
    if signature is None and not (data.idType and data.idNumber):
        raise BadRequest("A signature or an ID number is required")

    saved: list[str] = []
    try:
        signature_path = files.save_image(signature[0], signature[1], files.HANDOVER_DIR) if signature else None
        if signature_path:
            saved.append(signature_path)
        photo_path = files.save_image(photo[0], photo[1], files.HANDOVER_DIR) if photo else None
        if photo_path:
            saved.append(photo_path)

        handover = Handover(
            invoice_id=invoice.id, collectorName=data.collectorName.strip(),
            collectorPhone=collector_phone, idType=data.idType,
            idNumber=(data.idNumber or "").strip() or None, isReceiver=data.isReceiver,
            onCredit=owing, balance=balance if owing else 0.0, signaturePath=signature_path, photoPath=photo_path,
            note=(data.note or "").strip() or None, codeVerified=code_verified, logsId=current_user_id)
        handover.items = [HandoverItem(product_id=pid, cartons=c, logsId=current_user_id)
                          for pid, c in wanted.items() if c > 0]
        db.add(handover)
        db.flush()
        if final:
            status = EInvoiceStatus.DELIVERED.name if owing else EInvoiceStatus.COMPLETED.name
            invoice_dao.change_status(invoice, status, stamp(status), commit=False)
        _sms(db, invoice, handover, current_user_id, partial=not final,
             cartons=sum(wanted.values()))
        if owing:
            from ..notification.service import notify

            notify(db, "PAYMENT", "update", kind="CREDIT_HANDOVER", exclude=current_user_id,
                   title=f"Mzigo umekabidhiwa kwa mkopo · ankara {invoice.invoiceNumber}",
                   body=f"Deni TSh {whole(balance)} · {handover.collectorName}", link=f"invoice:{invoice.id}")
        db.commit()
    except Exception:
        db.rollback()
        for path in saved:
            files.remove(path)
        raise

    note(f"Ankara {invoice.invoiceNumber}: {'sehemu ya ' if not final else ''}mzigo (katoni "
         f"{sum(wanted.values()):g}) umekabidhiwa kwa {handover.collectorName}"
         + (f" ({handover.collectorPhone})" if handover.collectorPhone else "")
         + (f", deni TSh {whole(balance)}" if owing else ""))
    db.refresh(handover)
    return display(db, handover)


def _sms(db: Session, invoice, handover: Handover, user_id, partial: bool = False, cartons: float = 0) -> None:
    from ..sms import service as sms_service

    customer = invoice.customer[0] if invoice.customer else None
    if customer is None:
        return
    what = f"katoni {cartons:g} za mzigo" if partial else "mzigo"
    text = (f"Habari {customer.name}, {what} wa ankara {invoice.invoiceNumber} umekabidhiwa leo kwa "
            f"{handover.collectorName}{f' ({handover.collectorPhone})' if handover.collectorPhone else ''}. Kama si wewe au hukumtuma, tupigie "
            f"mara moja: {config.COMPANY_PHONES}. Ahsante.")
    sms_service.queue(db, ESmsStatus.HANDOVER, text=text, msisdn=customer.phoneNumber,
                      reference=invoice.invoiceNumber, invoice_id=invoice.id, logs_id=user_id, commit=False)


def display(db: Session, handover: Handover) -> schema.Display:
    from ..product.model import Product

    staff = UserDao(db).get(handover.logsId)
    computed = {"items", "partial", "hasSignature", "hasPhoto", "staffName"}
    out = schema.Display.model_validate({f: getattr(handover, f, None) for f in schema.Display.model_fields
                                         if f not in computed})
    out.hasSignature = bool(handover.signaturePath)
    out.hasPhoto = bool(handover.photoPath)
    out.staffName = f"{staff.firstName} {staff.lastName}" if staff else None
    if handover.items:
        names = dict(db.query(Product.id, Product.description)
                     .filter(Product.id.in_([i.product_id for i in handover.items])).all())
        out.items = [{"productId": str(i.product_id), "description": names.get(i.product_id, ""), "cartons": i.cartons}
                     for i in handover.items]
        total = dict(db.query(Product.id, Product.quantities).filter(Product.invoice_id == handover.invoice_id).all())
        out.partial = sum(i.cartons for i in handover.items) < sum((v or 1) for v in total.values()) - 1e-9
    return out


def _get(db: Session, invoice_id, handover_id=None) -> Handover:
    from ..core.dao import to_uuid

    q = db.query(Handover).filter(Handover.invoice_id == to_uuid(invoice_id))
    if handover_id:
        q = q.filter(Handover.id == to_uuid(handover_id))
    handover = q.order_by(Handover.created_at.desc()).first()
    if handover is None:
        raise NotFound("This cargo has not been handed over yet")
    return handover


def by_invoice(db: Session, invoice_id) -> schema.Display:
    return display(db, _get(db, invoice_id))


def status(db: Session, invoice_id) -> schema.Status:
    invoice = InvoiceDao(db).with_details(invoice_id)
    if invoice is None:
        raise NotFound("The Invoice does not exist")
    rows = remaining(invoice)
    handovers = sorted(invoice.handover or [], key=lambda h: h.created_at or 0)
    return schema.Status(handovers=[display(db, h) for h in handovers], remaining=rows,
                         complete=all(r.remaining <= 0 for r in rows),
                         needsCode=any(r.needsCode and r.remaining > 0 for r in rows))


def file_path(db: Session, invoice_id, kind: str, handover_id=None):
    handover = _get(db, invoice_id, handover_id)
    relative = handover.signaturePath if kind == "signature" else handover.photoPath if kind == "photo" else None
    if not relative:
        raise NotFound("File not found")
    return files.existing(relative)


def note_pdf(db: Session, invoice_id, handover_id=None) -> tuple[bytes, str]:
    handover = _get(db, invoice_id, handover_id)
    invoice = InvoiceDao(db).with_customer_and_products(invoice_id)
    debt = DebtDao(db).by_invoice(invoice_id)
    staff = UserDao(db).get(handover.logsId)

    def path(relative):
        try:
            return files.existing(relative) if relative else None
        except Exception:
            return None

    content = pdf.handover_note(handover, invoice, debt, staff, path(handover.signaturePath), path(handover.photoPath))
    return content, f"makabidhiano_{invoice.invoiceNumber}"
