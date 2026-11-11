from sqlalchemy.orm import Session

from ..core.audit import note
from ..core.enums import EInvoiceStatus, EPaymentKind, EPaymentStatus, ESmsStatus
from ..core.exceptions import BadRequest, NotFound
from ..core.utils import stamp, whole
from ..settings.institute.dao import InstituteDao
from . import schema, storage
from .dao import DebtDao, PaymentDao
from .model import Debt, Payment

TOLERANCE = 1.0  # TSh: chini ya hapa deni linahesabiwa limelipwa


def open_debt_if_missing(db: Session, invoice, total: float, commit: bool = True) -> Debt:
    dao = DebtDao(db)
    debt = dao.by_invoice(invoice.id)
    if debt is None:
        debt = dao.create(commit=False, amount=total, debt=total, paid=0.0, status=EPaymentStatus.OPEN.name,
                          days=0, storageCharge=0.0, discount=0.0, invoice_id=invoice.id, logsId=invoice.logsId)
        db.flush()
    storage.refresh(db, invoice, debt)
    if commit:
        db.commit()
    return debt


def total_due(debt: Debt) -> float:
    return (debt.amount or 0) + (debt.storageCharge or 0) - (debt.discount or 0)


def recalculate(db: Session, debt: Debt) -> Debt:
    """Inahesabu upya kilicholipwa, kilichobaki na hali ya deni (na ya invoice kama imekabidhiwa)."""
    db.flush()
    rows = db.query(Payment.kind, Payment.paid).filter(Payment.debt_id == debt.id).all()
    net = sum((paid or 0) * (-1 if kind == EPaymentKind.REFUND.name else 1) for kind, paid in rows)
    debt.paid = net
    debt.debt = total_due(debt) - net
    if debt.debt < TOLERANCE:
        debt.status = EPaymentStatus.PAID.name
    else:
        debt.status = EPaymentStatus.DEBT.name if net > 0 else EPaymentStatus.OPEN.name
    _sync_invoice(db, debt)
    return debt


def _sync_invoice(db: Session, debt: Debt) -> None:
    """Mzigo uliokabidhiwa kwa mkopo (DELIVERED) unakamilika (COMPLETED) deni likilipwa - na kinyume chake."""
    from ..invoice.dao import InvoiceDao

    dao = InvoiceDao(db)
    invoice = dao.get(debt.invoice_id)
    if invoice is None:
        return
    paid = debt.status == EPaymentStatus.PAID.name
    if invoice.status == EInvoiceStatus.DELIVERED.name and paid:
        dao.change_status(invoice, EInvoiceStatus.COMPLETED.name, stamp(EInvoiceStatus.COMPLETED.name), commit=False)
    elif invoice.status == EInvoiceStatus.COMPLETED.name and not paid and invoice.handover:
        dao.change_status(invoice, EInvoiceStatus.DELIVERED.name, stamp(EInvoiceStatus.DELIVERED.name), commit=False)


def _next_receipt(db: Session) -> str:
    row = (db.query(Payment.receiptNumber).filter(Payment.receiptNumber.isnot(None))
           .order_by(Payment.receiptNumber.desc()).first())
    last = int(row[0][1:]) if row and row[0] and row[0][1:].isdigit() else 0
    return f"R{last + 1:07d}"


def _debt_with_invoice(db: Session, debt_id):
    from ..invoice.dao import InvoiceDao

    debt = DebtDao(db).get(debt_id)
    if debt is None:
        raise NotFound("Payment not found")
    invoice = InvoiceDao(db).with_customer_and_products(debt.invoice_id)
    storage.refresh(db, invoice, debt)
    return debt, invoice


def create_payment(db: Session, data: schema.CreatePayment, current_user_id) -> Payment:
    from ..accounting.locks import ensure_open

    ensure_open(db)  # mwezi wa sasa ukifungwa na mhasibu, malipo mapya hayaandikwi
    debt, invoice = _debt_with_invoice(db, data.debtId)
    if debt.status == EPaymentStatus.PAID.name:
        raise BadRequest(f"Payment Completed Status : {debt.status}")
    if InstituteDao(db).get(data.instituteId) is None:
        raise NotFound("Financial Institute not found")

    currency = (data.currency or "TZS").strip().upper()
    rate = storage.currency_rate(db, currency)
    if not rate:
        raise BadRequest(f"No exchange rate for {currency}. Add it in Settings first")
    paid = round(data.paid * rate, 2)
    balance = debt.debt if debt.debt is not None else total_due(debt) - (debt.paid or 0)
    if paid > balance + TOLERANCE:
        raise BadRequest(f"Amount ({whole(paid)}) is more than the balance ({whole(balance)})")

    payment = PaymentDao(db).create(
        commit=False, paid=paid, kind=EPaymentKind.PAYMENT.name, currency=currency,
        amountOriginal=data.paid if currency not in storage.LOCAL_CODES else None,
        rate=rate if currency not in storage.LOCAL_CODES else None, note=(data.note or "").strip() or None,
        receiptNumber=_next_receipt(db), debt_id=debt.id, institute_id=data.instituteId, logsId=current_user_id)
    recalculate(db, debt)
    _receipt_sms(db, invoice, debt, payment, current_user_id)
    from ..notification.service import notify

    customer = invoice.customer[0].name if invoice and invoice.customer else ""
    notify(db, "PAYMENT", "update", kind="PAYMENT", exclude=current_user_id,
           title=f"Malipo TSh {whole(paid)} · ankara {invoice.invoiceNumber if invoice else '-'}",
           body=f"{customer} · baki TSh {whole(max(debt.debt or 0, 0))}",
           link=f"invoice:{invoice.id}" if invoice else None)
    db.commit()
    db.refresh(payment)
    number = invoice.invoiceNumber if invoice else "-"
    note(f"Malipo TSh {whole(paid)} ankara {number} (risiti {payment.receiptNumber}), baki {whole(debt.debt)}")
    return payment


def _receipt_sms(db: Session, invoice, debt: Debt, payment: Payment, user_id) -> None:
    from ..sms import service as sms_service

    customer = invoice.customer[0] if invoice and invoice.customer else None
    if customer is None:
        return
    left = max(debt.debt or 0, 0)
    tail = "Deni limekamilika. Ahsante kwa kuchagua huduma zetu." if left < TOLERANCE \
        else f"Kiasi kilichobaki ni TSh {whole(left)}/=."
    text = (f"Habari {customer.name}, tumepokea malipo ya TSh {whole(payment.paid)}/= kwa ankara "
            f"{invoice.invoiceNumber}. Risiti No. {payment.receiptNumber}. {tail}")
    sms_service.queue(db, ESmsStatus.RECEIPT, text=text, msisdn=customer.phoneNumber,
                      reference=payment.receiptNumber or invoice.invoiceNumber, invoice_id=invoice.id,
                      logs_id=user_id, commit=False)


def set_discount(db: Session, data: schema.Discount, current_user_id) -> Debt:
    debt, invoice = _debt_with_invoice(db, data.debtId)
    gross = (debt.amount or 0) + (debt.storageCharge or 0)
    if data.amount > gross:
        raise BadRequest(f"Discount cannot be more than the total ({whole(gross)})")
    old = debt.discount or 0
    debt.discount = data.amount
    debt.discountNote = data.note.strip()
    recalculate(db, debt)
    db.commit()
    note(f"Punguzo ankara {invoice.invoiceNumber if invoice else '-'}: TSh {whole(old)} -> {whole(data.amount)} "
         f"({data.note.strip()})")
    return search(db, schema.SearchPayment(invoiceId=debt.invoice_id))


def refund(db: Session, data: schema.Refund, current_user_id) -> Payment:
    from ..accounting.locks import ensure_open

    ensure_open(db)
    debt, invoice = _debt_with_invoice(db, data.debtId)
    if InstituteDao(db).get(data.instituteId) is None:
        raise NotFound("Financial Institute not found")
    if data.amount > (debt.paid or 0) + TOLERANCE:
        raise BadRequest(f"Refund cannot be more than what was paid ({whole(debt.paid)})")
    payment = PaymentDao(db).create(
        commit=False, paid=data.amount, kind=EPaymentKind.REFUND.name, currency="TZS", note=data.note.strip(),
        receiptNumber=_next_receipt(db), debt_id=debt.id, institute_id=data.instituteId, logsId=current_user_id)
    recalculate(db, debt)
    db.commit()
    db.refresh(payment)
    note(f"Pesa imerudishwa TSh {whole(data.amount)} ankara {invoice.invoiceNumber if invoice else '-'} "
         f"({data.note.strip()})")
    return payment


def search(db: Session, data: schema.SearchPayment) -> Debt:
    dao = DebtDao(db)
    debt = dao.by_invoice_with_payments(data.invoiceId)
    if debt is None:
        raise NotFound("Payment not found")
    from ..invoice.dao import InvoiceDao

    invoice = InvoiceDao(db).get(debt.invoice_id)
    if storage.refresh(db, invoice, debt):
        db.commit()
    return debt


def receipt_pdf(db: Session, payment_id) -> tuple[bytes, str]:
    from ..core import pdf
    from ..invoice.dao import InvoiceDao

    payment = PaymentDao(db).get(payment_id)
    if payment is None:
        raise NotFound("Payment not found")
    debt = DebtDao(db).get(payment.debt_id)
    invoice = InvoiceDao(db).with_customer_and_products(debt.invoice_id) if debt else None
    institute = InstituteDao(db).get(payment.institute_id)
    from ..user.dao import UserDao

    cashier = UserDao(db).get(payment.logsId)
    return pdf.receipt(payment, debt, invoice, institute, cashier), f"risiti_{payment.receiptNumber or payment.id}"
