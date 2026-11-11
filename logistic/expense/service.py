"""
Matumizi.

- Mtumiaji mwenye EXPENSES/insert anaandika matumizi ya ofisi yake (kulingana na role/ruhusa zake).
- Mhasibu (ACCOUNTING/update) au msimamizi akiandika -> yanaidhinishwa papo hapo; wengine -> PENDING
  mpaka mhasibu ayaidhinishe. Ripoti, salio na faida zinahesabu yaliyoidhinishwa tu.
"""
import os

from sqlalchemy.orm import Session

from ..core import files
from ..core.base_model import utc_now
from ..core.dao import to_uuid
from ..core.enums import Action, Module
from ..core.exceptions import BadRequest, NotFound, PermissionDenied
from ..core.permission import allowed
from ..core.scope import office_scope
from ..core.utils import whole
from ..settings.office.dao import OfficeDao
from . import schema
from .dao import ExpenseDao
from .model import Expense

PENDING, APPROVED, REJECTED = "PENDING", "APPROVED", "REJECTED"
RECEIPT_DIR = "YMG/Receipts"


def _check_office(db: Session, office_id) -> None:
    if OfficeDao(db).get(office_id) is None:
        raise NotFound("Office not found")


def _own_office(db: Session, office_id, current_user_id) -> None:
    scope = office_scope(db, current_user_id) if current_user_id else None
    if scope is not None and str(office_id) != str(scope):
        raise PermissionDenied("You can only record expenses for your own office")


def _approver(db: Session, user_id) -> bool:
    from ..saas.subscription.service import module_allowed

    # mpango usio na Uhasibu: hakuna idhini ya mhasibu - matumizi yanahesabiwa papo hapo (kama zamani)
    if not module_allowed(Module.ACCOUNTING.value):
        return bool(user_id)
    return bool(user_id) and allowed(db, user_id, Module.ACCOUNTING, Action.UPDATE)


def _fields(db: Session, data: schema.Create) -> dict:
    """Thamani za kuhifadhi (TSh + sarafu asili), baada ya kukagua kundi/akaunti/box."""
    from ..accounting.model import AccountCategory
    from ..package.model import Package
    from ..payment import storage
    from ..settings.institute.model import Institute

    currency = (data.currency or "TZS").strip().upper() or "TZS"
    rate = storage.currency_rate(db, currency)
    if not rate:
        raise BadRequest(f"Hakuna kiwango cha {currency}. Kiweke kwenye Mipangilio kwanza")
    if data.category_id is not None:
        cat = db.get(AccountCategory, data.category_id)
        if cat is None or cat.isBlocked or cat.kind != "EXPENSE":
            raise BadRequest("Kundi la matumizi halipo")
    if data.institute_id is not None:
        inst = db.get(Institute, data.institute_id)
        if inst is None or inst.isBlocked:
            raise BadRequest("Akaunti ya fedha haipo")
    if data.package_id is not None and db.get(Package, data.package_id) is None:
        raise BadRequest("Box halipo")
    local = rate == 1.0 and currency in ("TZS", "TSH")
    pay = (getattr(data, "payStatus", None) or "PAID").upper()
    if pay not in ("PAID", "PARTIAL", "CREDIT"):
        raise BadRequest("Hali ya malipo si sahihi")
    supplier = (getattr(data, "supplier", None) or "").strip() or None
    if pay != "PAID" and not supplier:
        raise BadRequest("Weka jina la tunayemdai kwa matumizi ya deni")
    paid_amount = getattr(data, "paidAmount", None)
    if pay == "PARTIAL" and not (paid_amount and 0 < paid_amount < data.amount):
        raise BadRequest("Kilicholipwa kiwe zaidi ya 0 na chini ya kiasi chote")
    paid = {"PAID": data.amount, "PARTIAL": paid_amount or 0, "CREDIT": 0.0}[pay]
    return {"details": data.details.strip(), "amount": round(data.amount * rate, 2), "currency": currency,
            "payStatus": pay, "supplier": supplier, "paidTzs": round(paid * rate, 2),
            "_paid_original": paid,
            "amountOriginal": None if local else data.amount, "rate": None if local else rate,
            "office_id": data.office_id, "category_id": data.category_id, "institute_id": data.institute_id,
            "package_id": data.package_id}


def display(db: Session, rows: list[Expense]) -> list[dict]:
    from ..accounting.model import AccountCategory
    from ..package.model import Package
    from ..settings.institute.model import Institute
    from ..user.model import User

    def names(model, ids, label):
        ids = {i for i in ids if i}
        return {r.id: label(r) for r in db.query(model).filter(model.id.in_(ids)).all()} if ids else {}

    cats = names(AccountCategory, [e.category_id for e in rows], lambda r: r.name)
    insts = names(Institute, [e.institute_id for e in rows], lambda r: r.name)
    boxes = names(Package, [e.package_id for e in rows], lambda r: r.boxId)
    users = names(User, [e.logsId for e in rows] + [e.approvedBy for e in rows],
                  lambda r: f"{r.firstName} {r.lastName}".strip() or r.username)
    out = []
    for e in rows:
        office = e.office[0] if isinstance(e.office, list) and e.office else (e.office if not isinstance(e.office, list) else None)
        out.append({
            "id": str(e.id), "details": e.details, "amount": e.amount, "currency": e.currency or "TZS",
            "amountOriginal": e.amountOriginal, "rate": e.rate,
            "office_id": str(e.office_id) if e.office_id else None,
            "office": [{"id": str(office.id), "name": office.name, "location": office.location,
                        "phoneNumber": office.phoneNumber, "isBlocked": office.isBlocked}] if office else [],
            "category_id": str(e.category_id) if e.category_id else None, "category": cats.get(e.category_id),
            "institute_id": str(e.institute_id) if e.institute_id else None, "institute": insts.get(e.institute_id),
            "package_id": str(e.package_id) if e.package_id else None, "boxId": boxes.get(e.package_id),
            "status": e.status or APPROVED, "rejectReason": e.rejectReason,
            "payStatus": e.payStatus or "PAID", "paidTzs": e.amount if e.paidTzs is None else e.paidTzs,
            "owedTzs": e.owedTzs, "supplier": e.supplier,
            "approvedBy": users.get(e.approvedBy), "approvedAt": e.approvedAt.isoformat() if e.approvedAt else None,
            "createdBy": users.get(e.logsId), "hasReceipt": bool(e.receipt),
            "created_at": e.created_at.isoformat() if e.created_at else None,
        })
    return out


def _one(db: Session, e: Expense) -> dict:
    db.refresh(e)
    return display(db, [e])[0]


def _get(db: Session, expense_id) -> Expense:
    expense = ExpenseDao(db).get(to_uuid(expense_id))
    if expense is None:
        raise NotFound("Expenses not found...")
    return expense


def _initial_payment(db: Session, expense: Expense, paid_original: float, user_id) -> None:
    """Malipo ya mwanzo ya matumizi (sehemu iliyolipwa) - yanatoka kwenye akaunti iliyolipa."""
    from .model import ExpensePayment

    db.query(ExpensePayment).filter(ExpensePayment.expense_id == expense.id,
                                    ExpensePayment.initial.is_(True)).delete(synchronize_session=False)
    paid_tzs = expense.paidTzs or 0
    if paid_tzs > 0:
        local = (expense.currency or "TZS") in ("TZS", "TSH") and not expense.rate
        db.add(ExpensePayment(expense_id=expense.id, amount=paid_tzs, currency=expense.currency or "TZS",
                              amountOriginal=None if local else paid_original, rate=expense.rate,
                              institute_id=expense.institute_id, initial=True, note="Malipo ya mwanzo",
                              logsId=user_id))


def create(db: Session, data: schema.Create, current_user_id) -> dict:
    from ..notification.service import notify

    from ..accounting.locks import ensure_open

    ensure_open(db)
    _own_office(db, data.office_id, current_user_id)
    _check_office(db, data.office_id)
    fields = _fields(db, data)
    paid_original = fields.pop("_paid_original")
    approver = _approver(db, current_user_id)
    expense = Expense(**fields, logsId=current_user_id, status=APPROVED if approver else PENDING,
                      approvedBy=current_user_id if approver else None, approvedAt=utc_now() if approver else None)
    db.add(expense)
    db.flush()
    _initial_payment(db, expense, paid_original, current_user_id)
    if not approver:
        notify(db, "ACCOUNTING", "update", kind="EXPENSE_PENDING", link="expenses",
               title=f"Matumizi yanasubiri idhini: TSh {whole(expense.amount)}", body=expense.details,
               exclude=current_user_id)
    db.commit()
    if approver and expense.package_id:
        from ..demand.service import refresh_package

        refresh_package(db, expense.package_id)
    return _one(db, expense)


def update(db: Session, data: schema.Update, current_user_id=None) -> dict:
    from ..accounting.locks import ensure_open
    from .model import ExpensePayment

    expense = _get(db, data.id)
    ensure_open(db, expense.created_at)
    _own_office(db, expense.office_id, current_user_id)
    _own_office(db, data.office_id, current_user_id)
    _check_office(db, data.office_id)
    approver = _approver(db, current_user_id)
    if expense.status in (None, APPROVED) and not approver:
        raise PermissionDenied("Matumizi yaliyoidhinishwa yanabadilishwa na mhasibu tu")
    if db.query(ExpensePayment.id).filter(ExpensePayment.expense_id == expense.id,
                                          ExpensePayment.initial.is_(False)).first():
        raise BadRequest("Deni la matumizi haya limeshaanza kulipwa - hayawezi kubadilishwa")
    fields = _fields(db, data)
    paid_original = fields.pop("_paid_original")
    for key, value in fields.items():
        setattr(expense, key, value)
    _initial_payment(db, expense, paid_original, current_user_id)
    if expense.status == REJECTED:  # yamerekebishwa -> yanarudi kusubiri idhini
        expense.status, expense.rejectReason = PENDING, None
    db.commit()
    return _one(db, expense)


def search(db: Session, f: schema.Search, current_user_id=None) -> list[dict]:
    scope = office_scope(db, current_user_id) if current_user_id else None
    if scope is not None:
        f.office_id = str(scope)
    return display(db, ExpenseDao(db).search(f))


def approve(db: Session, expense_id, user_id) -> dict:
    from ..core.audit import note

    from ..accounting.locks import ensure_open

    expense = _get(db, expense_id)
    ensure_open(db, expense.created_at)
    _own_office(db, expense.office_id, user_id)
    expense.status, expense.rejectReason = APPROVED, None
    expense.approvedBy, expense.approvedAt = to_uuid(user_id), utc_now()
    db.commit()
    note(f"Matumizi yameidhinishwa: {expense.details} TSh {whole(expense.amount)}")
    if expense.package_id:
        from ..demand.service import refresh_package

        refresh_package(db, expense.package_id)
    return _one(db, expense)


def reject(db: Session, expense_id, reason: str, user_id) -> dict:
    from ..core.audit import note
    from ..notification.model import Notification

    from ..accounting.locks import ensure_open

    expense = _get(db, expense_id)
    ensure_open(db, expense.created_at)
    _own_office(db, expense.office_id, user_id)
    expense.status, expense.rejectReason = REJECTED, reason.strip()
    expense.approvedBy, expense.approvedAt = to_uuid(user_id), utc_now()
    if expense.logsId and str(expense.logsId) != str(user_id):
        db.add(Notification(user_id=expense.logsId, kind="EXPENSE_REJECTED", link="expenses", isRead=False,
                            title=f"Matumizi yamekataliwa: TSh {whole(expense.amount)}"[:200],
                            body=f"{expense.details} - {reason.strip()}"[:500]))
    db.commit()
    note(f"Matumizi yamekataliwa: {expense.details} ({reason.strip()})")
    return _one(db, expense)


def delete(db: Session, expense_id, current_user_id=None) -> bool:
    from ..accounting.locks import ensure_open

    expense = _get(db, expense_id)
    ensure_open(db, expense.created_at)
    _own_office(db, expense.office_id, current_user_id)
    if current_user_id and expense.status in (None, APPROVED) \
            and not allowed(db, current_user_id, Module.ACCOUNTING, Action.DELETE):
        raise PermissionDenied("Matumizi yaliyoidhinishwa yanafutwa na mhasibu tu")
    receipt = expense.receipt
    ExpenseDao(db).delete(expense)
    files.remove(receipt)
    return True


def save_receipt(db: Session, expense_id, filename: str | None, content: bytes, user_id) -> dict:
    if not content:
        raise BadRequest("Hakuna picha")
    if len(content) > 8 * 1024 * 1024:
        raise BadRequest("Picha ni kubwa mno (MB 8 mwisho)")
    expense = _get(db, expense_id)
    _own_office(db, expense.office_id, user_id)
    ext = os.path.splitext(filename or "")[1].lower() or ".jpg"
    old = expense.receipt
    expense.receipt = files.save_image(f"receipt{ext}", content, directory=RECEIPT_DIR)
    db.commit()
    if old and old != expense.receipt:
        files.remove(old)
    return _one(db, expense)


def receipt_path(db: Session, expense_id, user_id):
    expense = _get(db, expense_id)
    _own_office(db, expense.office_id, user_id)
    if not expense.receipt:
        raise NotFound("Hakuna risiti")
    return files.existing(expense.receipt)


def pay(db: Session, expense_id, data: schema.Pay, user_id) -> dict:
    """Kulipa deni la matumizi (lote au sehemu) kutoka kwenye akaunti ya fedha."""
    from ..accounting.locks import ensure_open
    from ..core.audit import note
    from ..payment import storage
    from ..settings.institute.model import Institute
    from .model import ExpensePayment

    ensure_open(db)
    expense = _get(db, expense_id)
    if expense.status not in (None, APPROVED):
        raise BadRequest("Matumizi haya bado hayajaidhinishwa")
    owed = expense.owedTzs
    if owed <= 0:
        raise BadRequest("Matumizi haya hayana deni")
    code = (data.currency or "TZS").strip().upper() or "TZS"
    rate = storage.currency_rate(db, code)
    if not rate:
        raise BadRequest(f"Hakuna kiwango cha {code}")
    if data.institute_id is not None:
        inst = db.get(Institute, data.institute_id)
        if inst is None or inst.isBlocked:
            raise BadRequest("Akaunti ya fedha haipo")
    tzs = round(data.amount * rate, 2)
    if tzs > owed + 1:
        raise BadRequest(f"Kiasi kinazidi deni (TSh {whole(owed)})")
    tzs = min(tzs, owed)
    local = code in ("TZS", "TSH") and rate == 1.0
    db.add(ExpensePayment(expense_id=expense.id, amount=tzs, currency=code, amountOriginal=None if local else data.amount,
                          rate=None if local else rate, institute_id=data.institute_id, initial=False,
                          note=(data.note or "").strip() or None, logsId=user_id))
    expense.paidTzs = round((expense.paidTzs or 0) + tzs, 2)
    expense.payStatus = "PAID" if expense.owedTzs <= 0.009 else "PARTIAL"
    db.commit()
    note(f"Deni la matumizi limelipwa: {expense.details} {expense.supplier or ''} TSh {whole(tzs)}")
    return _one(db, expense)
