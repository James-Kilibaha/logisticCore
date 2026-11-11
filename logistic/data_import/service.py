"""
Kuingiza data ya zamani kutoka Excel (.xlsx):

- customers : Jina | Simu
- debts     : Jina | Simu | Deni (TSh) | Kilicholipwa (TSh) | Maelezo | Tarehe (YYYY-MM-DD)
              -> mteja (akikosekana anaundwa) + ankara ya "deni la zamani" + deni + malipo yaliyokwisha fanyika.

`dryRun=true` inakagua tu na kuonyesha matokeo bila kuhifadhi chochote.
"""
from datetime import datetime
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from ..core import excel
from ..core.audit import note
from ..core.enums import EInvoiceStatus, EPaymentKind, EPaymentStatus
from ..core.exceptions import BadRequest
from ..core.phone import try_normalize
from ..core.utils import title
from ..customer.model import Customer

KINDS = {
    "customers": ["Jina", "Simu"],
    "debts": ["Jina", "Simu", "Deni (TSh)", "Kilicholipwa (TSh)", "Maelezo", "Tarehe (YYYY-MM-DD)"],
}
_EXAMPLES = {
    "customers": [["Asha Juma", "0754111222"], ["Juma Ali", "0655333444"]],
    "debts": [["Asha Juma", "0754111222", 250000, 100000, "Mzigo wa Septemba", "2026-09-15"]],
}
MAX_ROWS = 5000


def template(kind: str) -> tuple[bytes, str]:
    if kind not in KINDS:
        raise BadRequest(f"kind must be one of {', '.join(KINDS)}")
    sheet = excel.Sheet(f"Import {kind}", KINDS[kind], _EXAMPLES[kind],
                        subtitle="Jaza kuanzia mstari wa 5 (futa mifano). Usibadilishe vichwa.")
    return excel.build([sheet]), f"template_{kind}"


def _rows(content: bytes, kind: str) -> list[tuple[int, list]]:
    try:
        wb = load_workbook(BytesIO(content), data_only=True, read_only=True)
    except Exception:
        raise BadRequest("The file is not a valid Excel (.xlsx) file")
    ws = wb.worksheets[0]
    expected = [h.lower() for h in KINDS[kind]]
    header_row = None
    rows = []
    for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        values = list(row)
        if header_row is None:
            first = [str(v).strip().lower() if v is not None else "" for v in values[:len(expected)]]
            if first[:2] == expected[:2]:
                header_row = idx
            continue
        if not any(v not in (None, "") for v in values):
            continue
        rows.append((idx, values + [None] * (len(expected) - len(values))))
        if len(rows) > MAX_ROWS:
            raise BadRequest(f"Too many rows (max {MAX_ROWS})")
    if header_row is None:
        raise BadRequest(f"Header row not found. Use the template: {', '.join(KINDS[kind])}")
    return rows


def _num(v) -> float | None:
    if v in (None, ""):
        return 0.0
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _date(v) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if v in (None, ""):
        return None
    try:
        return datetime.strptime(str(v).strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None


def run(db: Session, kind: str, content: bytes, dry_run: bool, user_id) -> dict:
    if kind not in KINDS:
        raise BadRequest(f"kind must be one of {', '.join(KINDS)}")
    rows = _rows(content, kind)
    errors, created, skipped = [], 0, 0
    seen_phones: set[str] = set()
    existing = {c.phoneNumber: c for c in db.query(Customer).all() if c.phoneNumber}
    by_name = {c.name.lower(): c for c in db.query(Customer).filter(Customer.phoneNumber.is_(None)).all()}

    for line, v in rows:
        name = title(str(v[0] or "").strip())
        raw_phone = str(v[1] or "").strip()
        phone = try_normalize(raw_phone)  # si lazima; ikiwekwa iwe +255XXXXXXXXX (au 07..)
        if not name or (raw_phone and phone is None):
            errors.append({"row": line, "message": "Jina halipo" if not name else
                           f"Simu si sahihi ({raw_phone}) - tumia +255XXXXXXXXX"})
            continue
        key = phone or f"name:{name.lower()}"
        if kind == "customers":
            if (phone and phone in existing) or (not phone and name.lower() in by_name) or key in seen_phones:
                skipped += 1
                continue
            seen_phones.add(key)
            if not dry_run:
                db.add(Customer(name=name, phoneNumber=phone, active=1, logsId=user_id))
            created += 1
            continue

        # ------------------------------------------------------------- madeni
        amount, paid = _num(v[2]), _num(v[3])
        if amount is None or paid is None or amount <= 0 or paid < 0 or paid > amount:
            errors.append({"row": line, "message": "Deni / kilicholipwa si sahihi"})
            continue
        if v[5] not in (None, "") and _date(v[5]) is None:
            errors.append({"row": line, "message": "Tarehe iwe YYYY-MM-DD"})
            continue
        if not dry_run:
            customer = existing.get(phone) if phone else by_name.get(name.lower())
            if customer is None:
                customer = Customer(name=name, phoneNumber=phone, active=1, logsId=user_id)
                db.add(customer)
                db.flush()
                if phone:
                    existing[phone] = customer
                else:
                    by_name[name.lower()] = customer
            _import_debt(db, customer, amount, paid, str(v[4] or "").strip(), _date(v[5]), user_id)
        created += 1

    if errors and not dry_run:
        db.rollback()
        return {"dryRun": dry_run, "saved": False, "created": 0, "skipped": skipped, "errors": errors,
                "rows": len(rows)}
    if not dry_run:
        db.commit()
        note(f"Import {kind}: {created} vimeingizwa, {skipped} vimerukwa")
    return {"dryRun": dry_run, "saved": not dry_run, "created": created, "skipped": skipped, "errors": errors,
            "rows": len(rows)}


def _import_debt(db: Session, customer, amount: float, paid: float, description: str, when: datetime | None,
                 user_id) -> None:
    from ..invoice.dao import InvoiceDao
    from ..invoice.model import Invoice
    from ..invoice.service import _next_number
    from ..payment import service as payment_service
    from ..payment.model import Debt, Payment
    from ..product.model import Product

    stamp_at = (when or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S")
    status = EInvoiceStatus.COMPLETED.name if paid >= amount else EInvoiceStatus.DELIVERED.name
    invoice = Invoice(invoiceNumber=_next_number(InvoiceDao(db)), status=status,
                      history=f"IMPORT_{stamp_at},{status}_{stamp_at}", customer_id=customer.id, logsId=user_id)
    db.add(invoice)
    db.flush()
    db.add(Product(description=f"Deni la zamani{': ' + description if description else ''}"[:200],
                   unitPrice=amount, quantities=1, weight=0, carrierType="AIR", invoice_id=invoice.id, logsId=user_id))
    debt = Debt(amount=amount, debt=amount, paid=0.0, status=EPaymentStatus.OPEN.name, days=0, storageCharge=0.0,
                discount=0.0, invoice_id=invoice.id, logsId=user_id)
    db.add(debt)
    db.flush()
    if paid > 0:
        db.add(Payment(paid=paid, kind=EPaymentKind.PAYMENT.name, currency="TZS", note="Malipo ya zamani (import)",
                       debt_id=debt.id, logsId=user_id))
    payment_service.recalculate(db, debt)
