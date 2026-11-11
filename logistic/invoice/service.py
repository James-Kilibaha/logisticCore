from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config
from ..core import files
from ..core.audit import note
from ..core.scope import office_scope, user_office
from ..core.enums import EInvoiceStatus
from ..core.exceptions import BadRequest, NotFound
from ..core.utils import join_ids, money, split_ids, stamp
from ..customer.dao import CustomerDao
from ..payment import service as payment_service
from . import schema
from .dao import InvoiceDao
from .model import Invoice


def _get_or_404(dao: InvoiceDao, invoice_id) -> Invoice:
    invoice = dao.get(invoice_id)
    if invoice is None:
        raise NotFound("The Invoice does not exist")
    return invoice


def _next_number(dao: InvoiceDao) -> str:
    last = dao.last_number()
    return str(int(last) + 1).zfill(7) if last and last.isdigit() else "0000000"


def create(db: Session, data: schema.Create, current_user_id) -> Invoice:
    if CustomerDao(db).get(data.customer_id) is None:
        raise NotFound("The Customer does not exist")
    from ..saas.subscription.service import check_limit

    check_limit(db, "invoicesThisMonth")  # mipaka ya mpango wa subscription
    # Mtumiaji aliyefungiwa ofisi moja anaunda ankara za ofisi yake tu.
    office_id = office_scope(db, current_user_id) or data.office_id or user_office(db, current_user_id)

    dao = InvoiceDao(db)
    status = EInvoiceStatus.OPEN.name
    history = data.history or stamp(status)
    for _ in range(3):  # kama watumiaji wawili wameunda kwa wakati mmoja, jaribu namba inayofuata
        try:
            return dao.create(invoiceNumber=_next_number(dao), status=status, history=history,
                              customer_id=data.customer_id, office_id=office_id, logsId=current_user_id)
        except IntegrityError:
            db.rollback()
    raise NotFound("Could not create invoice number, try again")


def list_all(db: Session):
    return InvoiceDao(db).all_ordered()


def by_customer(db: Session, customer_id):
    return InvoiceDao(db).by_customer(customer_id)


def by_status(db: Session, status: str):
    return InvoiceDao(db).by_status(status)


def search(db: Session, f: schema.Search, current_user_id=None):
    scope = office_scope(db, current_user_id) if current_user_id else None
    return InvoiceDao(db).search(f, scope_office=scope)


def set_office(db: Session, data: schema.SetOffice, current_user_id) -> Invoice:
    if office_scope(db, current_user_id) is not None:
        from ..core.exceptions import PermissionDenied

        raise PermissionDenied("Only users who see all offices can move invoices between offices")
    dao = InvoiceDao(db)
    invoice = _get_or_404(dao, data.id)
    if data.office_id is not None:
        from ..settings.office.dao import OfficeDao

        if OfficeDao(db).get(data.office_id) is None:
            raise NotFound("Office not found")
    note(f"Ankara {invoice.invoiceNumber}: ofisi imebadilishwa")
    return dao.update(invoice, office_id=data.office_id)


def change_status(db: Session, data: schema.UpdateStatus) -> Invoice:
    dao = InvoiceDao(db)
    return dao.change_status(_get_or_404(dao, data.id), data.status, data.history or stamp(data.status))


def block(db: Session, data: schema.Block) -> Invoice:
    return change_status(db, schema.UpdateStatus(id=data.id, status=data.status, history=data.history))


def created_cargo_products(db: Session, data: schema.CustomerStatus):
    invoices = InvoiceDao(db).by_customer_and_status(data.customer_id, data.status, with_products=True)
    if not invoices:
        raise NotFound("The Cargo Batch or (Order) does not exist")
    return invoices


def customer_invoices(db: Session, data: schema.CustomerStatus):
    invoices = InvoiceDao(db).by_customer_and_status(data.customer_id, data.status)
    if not invoices:
        raise NotFound("The Customer does not have Order yet")
    return invoices


def generate_pdf(db: Session, data: schema.InvoiceStatusRef):
    """
    Inatengeneza PDF ya invoice (moja kwa moja, bila MS Word/LibreOffice), inafungua deni (kama halipo)
    na kurudisha njia ya PDF. Inatumika na /api/invoice/generate-invoice na /api/store/generate-invoice.
    """
    from ..core import pdf
    from ..core.utils import product_cbm

    dao = InvoiceDao(db)
    invoice = dao.with_details(data.id) if data.id else None
    if invoice is None or (data.status is not None and invoice.status != data.status):
        raise NotFound("The Invoice does not exist (or status does not match)")

    total = sum(p.unitPrice or 0 for p in invoice.product)
    rows = [{"description": p.description, "track": p.trackNumber, "carrier": p.carrierType,
             "quantities": p.quantities, "weight": p.weight, "cbm": product_cbm(p), "amount": p.unitPrice or 0}
            for p in invoice.product]

    payment_service.open_debt_if_missing(db, invoice, total, commit=False)
    extra_rows, _ = _extra_rows(db, invoice)
    customer = invoice.customer[0] if invoice.customer else None
    receiver = invoice.receiver[0] if invoice.receiver else None
    relative = f"{files.INVOICE_DIR}/invoice_{invoice.invoiceNumber}"
    target = files.absolute(relative).with_suffix(".pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf.invoice(invoice, customer, rows, extra_rows, receiver, config.PUBLIC_TRACK_URL or None))

    dao.update(invoice, path=relative)
    return target


def _extra_rows(db: Session, invoice) -> tuple[list[tuple[str, float]], float]:
    """Mistari ya gharama za stoo (+) na punguzo (-), kama deni lipo tayari."""
    from ..payment import storage
    from ..payment.dao import DebtDao

    debt = DebtDao(db).by_invoice(invoice.id)
    if debt is None:
        return [], 0.0
    storage.refresh(db, invoice, debt)
    rows: list[tuple[str, float]] = []
    if debt.storageCharge:
        rows.append((f"Gharama za stoo (siku {storage.chargeable_days(debt.days or 0)} baada ya "
                     f"{config.DAYS_TO_CHARGE} za bure)", float(debt.storageCharge)))
    if debt.discount:
        rows.append((f"Punguzo{': ' + debt.discountNote[:30] if debt.discountNote else ''}", -float(debt.discount)))
    return rows, sum(v for _, v in rows)


BLOCKED_STATUSES = (EInvoiceStatus.BLOCKED.name, EInvoiceStatus.BLOCK.name)


def _purge(db: Session, invoice: Invoice) -> None:
    """Inafuta invoice na kila kilichoiunganisha (bila commit)."""
    from ..package.dao import PackageDao  # kuepuka import ya mzunguko

    product_ids = {str(p.id) for p in invoice.product}
    weights = {str(p.id): (p.weight or 0) for p in invoice.product}
    invoice_id = str(invoice.id)

    # ondoa bidhaa na invoice kwenye mabox yoyote
    for package in PackageDao(db).all():
        products = split_ids(package.productList)
        invoices = split_ids(package.invoiceList)
        if not (product_ids & set(products)) and invoice_id not in invoices:
            continue
        removed = [pid for pid in products if pid in product_ids]
        package.productList = join_ids([pid for pid in products if pid not in product_ids])
        package.invoiceList = join_ids([iid for iid in invoices if iid != invoice_id])
        if not package.isBoxClose:
            package.weight = max((package.weight or 0) - sum(weights[pid] for pid in removed), 0.0)
        db.add(package)

    for debt in invoice.debt:
        for payment in debt.payment:
            db.delete(payment)
        db.delete(debt)
    for sms in invoice.sms:
        db.delete(sms)
    from ..claim.model import CargoClaim

    claim_photos = [c.photoPath for c in db.query(CargoClaim).filter(CargoClaim.invoice_id == invoice.id)]
    db.query(CargoClaim).filter(CargoClaim.invoice_id == invoice.id).delete(synchronize_session=False)
    for receiver in invoice.receiver:
        db.delete(receiver)
    handover_files = []
    for handover in invoice.handover:
        handover_files += [handover.signaturePath, handover.photoPath]
        db.delete(handover)
    images = [p.path for p in invoice.product]
    for product in invoice.product:
        db.delete(product)
    pdf = f"{invoice.path}.pdf" if invoice.path else None
    db.delete(invoice)
    db.flush()
    for path in images + handover_files + claim_photos + [pdf]:
        try:
            files.remove(path)
        except OSError:
            pass


def delete(db: Session, invoice_id) -> bool:
    """Ni invoice iliyozuiwa (BLOCKED) pekee inayoweza kufutwa."""
    invoice = _get_or_404(InvoiceDao(db), invoice_id)
    if invoice.status not in BLOCKED_STATUSES:
        raise BadRequest("Only blocked invoices can be deleted")
    customer = invoice.customer[0].name if invoice.customer else "-"
    note(f"Ankara {invoice.invoiceNumber} ({customer}) imefutwa, mizigo {len(invoice.product)}")
    _purge(db, invoice)
    db.commit()
    return True


def delete_blocked(db: Session) -> dict:
    """Inafuta invoice zote zilizozuiwa; inarudisha idadi iliyofutwa."""
    invoices = InvoiceDao(db).find_all(Invoice.status.in_(BLOCKED_STATUSES))
    numbers = [i.invoiceNumber for i in invoices]
    for invoice in invoices:
        _purge(db, invoice)
    db.commit()
    note(f"Ankara {len(numbers)} zilizozuiwa zimefutwa: {', '.join(numbers)}"[:500])
    return {"deleted": len(invoices)}
