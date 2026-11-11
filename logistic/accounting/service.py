"""
Uhasibu rahisi: akaunti za fedha na salio, mapato mengine, uhamisho, makundi na Faida/Hasara.

Salio la akaunti = salio la kuanzia
                 + malipo ya ankara yaliyopokelewa kupitia akaunti hiyo - pesa zilizorudishwa (refund)
                 + mapato mengine + uhamisho ulioingia
                 - matumizi yaliyoidhinishwa - uhamisho uliotoka
(kuanzia `openingDate` kama imewekwa).

Faida/Hasara (msingi wa pesa iliyopokelewa):
    mapato   = malipo ya ankara (- refund) + mapato mengine
    gharama  = matumizi yaliyoidhinishwa + gharama za mabox (nauli, ushuru, clearing ...)
    faida    = mapato - gharama
"""
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.audit import note
from ..core.dao import to_uuid
from ..core.exceptions import BadRequest, Conflict, NotFound
from ..core.scope import office_scope
from ..core.utils import day_range, local_midnight_utc, local_now, parse_date, to_local, whole
from ..expense.dao import approved_filter
from ..expense.model import Expense
from ..invoice.model import Invoice
from ..payment.model import Debt, Payment
from ..settings.institute.model import Institute
from ..settings.office.model import Office
from . import schema
from .model import KINDS, AccountCategory, Income, Transfer

NO_CATEGORY = "Bila kundi"

DEFAULT_CATEGORIES = {
    "EXPENSE": ["Mafuta", "Mishahara", "Kodi ya pango", "Umeme na maji", "Mawasiliano (simu / intaneti)",
                "Usafiri", "Forodha na ushuru", "Matengenezo", "Vifaa vya ofisi", "Posho", "Mengineyo"],
    "INCOME": ["Huduma nyingine", "Kodi ya pango", "Mengineyo"],
}
KIND_LABEL = {"CASH": "Cash", "BANK": "Benki", "MOBILE": "Simu"}


# ------------------------------------------------------------------ msaada
def ensure_defaults(db: Session, owner_id=None) -> None:
    """Makundi ya kuanzia (mara moja tu - kama hakuna kundi lolote)."""
    if db.query(AccountCategory.id).first() is not None:
        return
    if owner_id is None:
        from ..user.model import User

        owner = db.query(User.id).order_by(User.created_at).first()
        if owner is None:
            return
        owner_id = owner[0]
    for kind, names in DEFAULT_CATEGORIES.items():
        for name in names:
            db.add(AccountCategory(name=name, kind=kind, logsId=to_uuid(owner_id)))
    db.commit()


def _scope(db: Session, user_id, office=None):
    """Mtumiaji aliyefungiwa ofisi moja anaona ofisi yake tu."""
    scope = office_scope(db, user_id) if user_id else None
    return scope if scope is not None else to_uuid(office) if office else None


def _period(start_date: str | None, end_date: str | None) -> tuple[datetime, datetime, str, str]:
    today = local_now().date()
    s = parse_date(start_date) or today.replace(day=1)
    e = parse_date(end_date) or today
    if e < s:
        raise BadRequest("Tarehe ya mwisho iko kabla ya ya kuanzia")
    start, end = day_range(s.isoformat(), e.isoformat())
    return start, end, s.isoformat(), e.isoformat()


def _label(s: str, e: str) -> str:
    return f"{parse_date(s):%d/%m/%Y} - {parse_date(e):%d/%m/%Y}"


def _rate(db: Session, currency: str) -> tuple[str, float]:
    from ..payment import storage

    code = (currency or "TZS").strip().upper() or "TZS"
    rate = storage.currency_rate(db, code)
    if not rate:
        raise BadRequest(f"Hakuna kiwango cha {code}. Kiweke kwenye Mipangilio kwanza")
    return code, rate


def _account(db: Session, account_id) -> Institute:
    inst = db.get(Institute, to_uuid(account_id))
    if inst is None or inst.isBlocked:
        raise NotFound("Akaunti ya fedha haipo")
    return inst


def _category(db: Session, category_id, kind: str) -> None:
    if category_id is None:
        return
    cat = db.get(AccountCategory, category_id)
    if cat is None or cat.isBlocked or cat.kind != kind:
        raise BadRequest("Kundi halipo")


def _users(db: Session, ids) -> dict:
    from ..user.model import User

    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: (f"{u.firstName} {u.lastName}".strip() or u.username)
            for u in db.query(User).filter(User.id.in_(ids)).all()}


# ------------------------------------------------------------------ makundi
def categories(db: Session, kind: str | None = None, include_blocked: bool = False, user_id=None) -> list[dict]:
    ensure_defaults(db, user_id)
    q = db.query(AccountCategory)
    if kind:
        q = q.filter(AccountCategory.kind == kind.upper())
    if not include_blocked:
        q = q.filter(AccountCategory.isBlocked.is_(False))
    return [{"id": str(c.id), "name": c.name, "kind": c.kind, "description": c.description,
             "isBlocked": c.isBlocked} for c in q.order_by(AccountCategory.kind, AccountCategory.name).all()]


def _check_kind(kind: str) -> str:
    kind = (kind or "EXPENSE").upper()
    if kind not in KINDS:
        raise BadRequest("Aina ya kundi si sahihi")
    return kind


def save_category(db: Session, data: schema.CategorySave, user_id, category_id=None) -> dict:
    kind = _check_kind(data.kind)
    name = data.name.strip()
    other = (db.query(AccountCategory)
             .filter(func.lower(AccountCategory.name) == name.lower(), AccountCategory.kind == kind,
                     AccountCategory.isBlocked.is_(False)))
    if category_id is not None:
        other = other.filter(AccountCategory.id != to_uuid(category_id))
    if other.first():
        raise Conflict("Kundi lenye jina hili lipo tayari")
    if category_id is None:
        cat = AccountCategory(name=name, kind=kind, description=(data.description or "").strip() or None,
                              logsId=user_id)
        db.add(cat)
    else:
        cat = db.get(AccountCategory, to_uuid(category_id))
        if cat is None:
            raise NotFound("Kundi halipo")
        cat.name, cat.kind = name, kind
        cat.description = (data.description or "").strip() or None
    db.commit()
    return {"id": str(cat.id), "name": cat.name, "kind": cat.kind, "description": cat.description,
            "isBlocked": cat.isBlocked}


def delete_category(db: Session, category_id) -> dict:
    cat = db.get(AccountCategory, to_uuid(category_id))
    if cat is None:
        raise NotFound("Kundi halipo")
    used = (db.query(Expense.id).filter(Expense.category_id == cat.id).first()
            or db.query(Income.id).filter(Income.category_id == cat.id).first())
    if used:  # historia inabaki - linafichwa tu
        cat.isBlocked = True
        db.commit()
        return {"deleted": True, "archived": True}
    db.delete(cat)
    db.commit()
    return {"deleted": True, "archived": False}


# ------------------------------------------------------------------ akaunti na salio
def _since(inst: Institute) -> datetime | None:
    d = parse_date(inst.openingDate) if inst.openingDate else None
    return local_midnight_utc(d) if d else None


def _local(code: str | None) -> bool:
    return (code or "TZS").upper() in ("TZS", "TSH")


def _acc_rate(db: Session, inst: Institute) -> float:
    """Kiwango cha sasa cha sarafu ya akaunti (TSh kwa 1). TSh = 1."""
    from ..payment import storage

    if _local(inst.currencyType):
        return 1.0
    return storage.currency_rate(db, inst.currencyType.upper()) or 1.0


def _native(tzs: float, currency: str | None, original: float | None, inst: Institute, rate: float) -> float:
    """Kiasi kwa sarafu ya akaunti: asili kama sarafu ni ileile, vinginevyo TSh / kiwango cha sasa."""
    if _local(inst.currencyType):
        return tzs or 0.0
    if (currency or "TZS").upper() == inst.currencyType.upper() and original is not None:
        return original
    return (tzs or 0.0) / rate if rate else (tzs or 0.0)


def _lines(db: Session, inst: Institute, lo: datetime | None, hi: datetime | None, detail: bool = True) -> list[dict]:
    """Kila pesa iliyoingia/kutoka kwenye akaunti ndani ya [lo, hi): TSh na sarafu ya akaunti."""
    from ..customer.model import Customer
    from ..expense.model import ExpensePayment
    from ..package.model import Package
    from ..shipment.model import CostPayment, PackageCost
    from .model import Equity

    rate = _acc_rate(db, inst)
    out: list[dict] = []

    def win(q, col):
        if lo is not None:
            q = q.filter(col >= lo)
        if hi is not None:
            q = q.filter(col < hi)
        return q

    def add(at, typ, details, tzs, currency, original, money_in: bool, ref="", native=None):
        n = _native(tzs, currency, original, inst, rate) if native is None else native
        out.append({"at": at, "type": typ, "ref": ref, "details": details,
                    "moneyIn": (tzs or 0) if money_in else 0.0, "moneyOut": 0.0 if money_in else (tzs or 0),
                    "nativeIn": n if money_in else 0.0, "nativeOut": 0.0 if money_in else n})

    q = (db.query(Payment, Invoice.invoiceNumber, Customer.name)
         .join(Debt, Debt.id == Payment.debt_id).join(Invoice, Invoice.id == Debt.invoice_id)
         .outerjoin(Customer, Customer.id == Invoice.customer_id).filter(Payment.institute_id == inst.id))
    for p, number, who in win(q, Payment.created_at).all():
        refund = p.kind == "REFUND"
        who = (who or "").strip()
        add(p.created_at, "REFUND" if refund else "PAYMENT",
            f"{'Refund' if refund else 'Malipo'} ankara #{number}" + (f" - {who}" if who else ""),
            p.paid, p.currency, p.amountOriginal, not refund, ref=p.receiptNumber or (f"#{number}" if number else ""))
    for x in win(db.query(Income).filter(Income.institute_id == inst.id, Income.isBlocked.is_(False)),
                 Income.created_at).all():
        add(x.created_at, "INCOME", x.details, x.amount, x.currency, x.amountOriginal, True)
    # matumizi ya zamani (bila rekodi za malipo): kiasi chote kutoka akaunti yake
    for x in win(db.query(Expense).filter(Expense.institute_id == inst.id, approved_filter(),
                                          Expense.payStatus.is_(None)), Expense.created_at).all():
        add(x.created_at, "EXPENSE", x.details, x.amount, x.currency, x.amountOriginal, False)
    for ep, x in win(db.query(ExpensePayment, Expense).join(Expense, Expense.id == ExpensePayment.expense_id)
                     .filter(ExpensePayment.institute_id == inst.id, approved_filter()), ExpensePayment.created_at).all():
        add(ep.created_at, "EXPENSE", x.details + ("" if ep.initial else " (deni)") + (f" - {x.supplier}" if x.supplier else ""),
            ep.amount, ep.currency, ep.amountOriginal, False)
    names = {i.id: i.name for i in db.query(Institute).all()} if detail else {}
    for t in win(db.query(Transfer).filter(Transfer.isBlocked.is_(False),
                                           (Transfer.from_id == inst.id) | (Transfer.to_id == inst.id)),
                 Transfer.created_at).all():
        outgoing = t.from_id == inst.id
        other = names.get(t.to_id if outgoing else t.from_id, "?")
        native = t.fromAmount if outgoing else t.toAmount
        add(t.created_at, "TRANSFER_OUT" if outgoing else "TRANSFER_IN",
            (f"Uhamisho kwenda {other}" if outgoing else f"Uhamisho kutoka {other}") + (f" - {t.note}" if t.note else ""),
            t.amount, None, None, not outgoing, native=native)
    for cp, cost, box in win(db.query(CostPayment, PackageCost, Package.boxId)
                             .join(PackageCost, PackageCost.id == CostPayment.cost_id)
                             .join(Package, Package.id == PackageCost.package_id)
                             .filter(CostPayment.institute_id == inst.id), CostPayment.created_at).all():
        add(cp.created_at, "BOX_COST",
            f"Gharama ya box {box} ({_BOX_LABEL.get(cost.category, cost.category)})"
            + (f" - {cost.supplier}" if cost.supplier else ""), cp.amount, cp.currency, cp.amountOriginal, False,
            ref=f"Box {box}")
    for e in win(db.query(Equity).filter(Equity.institute_id == inst.id, Equity.isBlocked.is_(False)),
                 Equity.created_at).all():
        capital = e.kind == "CAPITAL"
        add(e.created_at, "CAPITAL" if capital else "DRAWING",
            ("Mtaji" if capital else "Pesa za mmiliki") + (f": {e.owner}" if e.owner else "")
            + (f" - {e.details}" if e.details else ""), e.amount, e.currency, e.amountOriginal, capital)
    from ..assets.model import FixedAsset

    for fa in win(db.query(FixedAsset).filter(FixedAsset.institute_id == inst.id, FixedAsset.isBlocked.is_(False)),
                  FixedAsset.created_at).all():
        add(fa.created_at, "ASSET_BUY", f"Ununuzi wa mali: {fa.name}", fa.cost, fa.currency, fa.amountOriginal, False)
    for fa in db.query(FixedAsset).filter(FixedAsset.disposal_institute_id == inst.id, FixedAsset.isBlocked.is_(False),
                                          FixedAsset.disposedOn.isnot(None)).all():
        at = local_midnight_utc(parse_date(fa.disposedOn))
        if (lo is None or at >= lo) and (hi is None or at < hi) and (fa.disposalAmount or 0) > 0:
            add(at, "ASSET_SALE", f"Mauzo ya mali: {fa.name}", fa.disposalAmount, None, None, True)
    out.sort(key=lambda r: r["at"] or datetime.min)
    return out


def _movements(db: Session, inst: Institute, start: datetime | None, end: datetime | None) -> dict:
    lines = _lines(db, inst, start, end, detail=False)
    money_in = sum(r["moneyIn"] for r in lines)
    money_out = sum(r["moneyOut"] for r in lines)
    native = sum(r["nativeIn"] - r["nativeOut"] for r in lines)
    return {"moneyIn": round(money_in, 2), "moneyOut": round(money_out, 2), "net": round(money_in - money_out, 2),
            "nativeNet": round(native, 2)}


def _balance_at(db: Session, inst: Institute, at: datetime | None) -> float:
    """Salio kwa sarafu ya akaunti (salio la kuanzia ni kwa sarafu ya akaunti)."""
    since = _since(inst)
    if at is not None and since is not None and at <= since:
        return round(inst.openingBalance or 0, 2)
    return round((inst.openingBalance or 0) + _movements(db, inst, since, at)["nativeNet"], 2)


def _account_row(db: Session, inst: Institute, offices: dict, with_balance: bool = True) -> dict:
    row = {"id": str(inst.id), "name": inst.name, "accountNo": inst.accountNo,
           "currencyType": (inst.currencyType or "TZS").upper(),
           "kind": inst.kind or "BANK", "office_id": str(inst.office_id) if inst.office_id else None,
           "office": offices.get(inst.office_id), "isBlocked": inst.isBlocked}
    if with_balance:
        native = _balance_at(db, inst, None)
        rate = _acc_rate(db, inst)
        row.update({"openingBalance": round(inst.openingBalance or 0, 2), "openingDate": inst.openingDate,
                    "nativeBalance": native, "rate": rate,
                    "balance": round(native * rate, 2)})   # TSh (kwa jumla na mizania)
    return row


def _accounts_query(db: Session, office=None):
    q = db.query(Institute).filter(Institute.isBlocked.is_(False))
    if office is not None:
        q = q.filter((Institute.office_id == office) | (Institute.office_id.is_(None)))
    return q.order_by(Institute.name)


def accounts(db: Session, user_id, office=None, with_balance: bool = True) -> dict:
    office = _scope(db, user_id, office)
    offices = {o.id: o.name for o in db.query(Office).all()}
    rows = [_account_row(db, i, offices, with_balance) for i in _accounts_query(db, office).all()]
    out = {"items": rows}
    if with_balance:
        out["total"] = round(sum(r["balance"] for r in rows), 2)
        out["byKind"] = {k: round(sum(r["balance"] for r in rows if r["kind"] == k), 2) for k in KIND_LABEL}
        by_cur: dict[str, float] = {}
        for r in rows:
            by_cur[r["currencyType"]] = round(by_cur.get(r["currencyType"], 0) + r["nativeBalance"], 2)
        out["byCurrency"] = by_cur
    return out


def save_account(db: Session, data: schema.AccountSave, user_id, account_id=None) -> dict:
    import uuid

    kind = (data.kind or "BANK").upper()
    if kind not in schema.ACCOUNT_KINDS:
        raise BadRequest("Aina ya akaunti si sahihi")
    if data.openingDate and parse_date(data.openingDate) is None:
        raise BadRequest("Tarehe ya salio la kuanzia si sahihi (YYYY-MM-DD)")
    if data.office_id is not None and db.get(Office, data.office_id) is None:
        raise NotFound("Office not found")
    currency = (data.currencyType or "TZS").strip().upper() or "TZS"
    if not _local(currency):
        _rate(db, currency)  # sarafu lazima iwe na kiwango
    number = (data.accountNo or "").strip()
    if not number:
        if kind != "CASH":
            raise BadRequest("Weka namba ya akaunti")
        number = f"CASH-{uuid.uuid4().hex[:6].upper()}"
    other = db.query(Institute).filter(Institute.accountNo == number)
    if account_id is not None:
        other = other.filter(Institute.id != to_uuid(account_id))
    if other.first():
        raise Conflict("Namba hii ya akaunti ipo tayari")
    fields = {"name": data.name.strip(), "accountNo": number, "currencyType": currency,
              "kind": kind, "office_id": data.office_id, "openingBalance": round(data.openingBalance or 0, 2),
              "openingDate": parse_date(data.openingDate).isoformat() if data.openingDate else None}
    if account_id is None:
        inst = Institute(**fields, logsId=user_id)
        db.add(inst)
        msg = f"Akaunti mpya ya fedha: {inst.name} ({currency})"
    else:
        inst = _account(db, account_id)
        for k, v in fields.items():
            setattr(inst, k, v)
        msg = f"Akaunti ya fedha '{inst.name}' imebadilishwa (salio la kuanzia {currency} {whole(inst.openingBalance)})"
    db.commit()
    note(msg)
    offices = {o.id: o.name for o in db.query(Office).all()}
    return _account_row(db, inst, offices)


def delete_account(db: Session, account_id) -> dict:
    from ..cashup.model import CashUpLine
    from ..expense.model import ExpensePayment
    from ..shipment.model import CostPayment
    from .model import Equity

    inst = _account(db, account_id)
    used = any(q.first() is not None for q in (
        db.query(Payment.id).filter(Payment.institute_id == inst.id),
        db.query(CashUpLine.id).filter(CashUpLine.institute_id == inst.id),
        db.query(Expense.id).filter(Expense.institute_id == inst.id),
        db.query(ExpensePayment.id).filter(ExpensePayment.institute_id == inst.id),
        db.query(Income.id).filter(Income.institute_id == inst.id),
        db.query(Equity.id).filter(Equity.institute_id == inst.id),
        db.query(Transfer.id).filter((Transfer.from_id == inst.id) | (Transfer.to_id == inst.id)),
        db.query(CostPayment.id).filter(CostPayment.institute_id == inst.id)))
    if used:
        inst.isBlocked = True
        db.commit()
        return {"deleted": True, "archived": True}
    db.delete(inst)
    db.commit()
    return {"deleted": True, "archived": False}


def statement(db: Session, account_id, start_date: str | None, end_date: str | None) -> dict:
    """Mwenendo wa akaunti: salio la kuanzia, kila pesa iliyoingia / kutoka, na salio baada ya kila mstari.
    Kiasi chote ni kwa SARAFU YA AKAUNTI (TSh pia vimeonyeshwa: moneyInTzs / moneyOutTzs)."""
    inst = _account(db, account_id)
    start, end, s, e = _period(start_date, end_date)
    since = _since(inst)
    lo = max(start, since) if since is not None else start
    opening = _balance_at(db, inst, lo)
    lines = _lines(db, inst, lo, end)
    running = opening
    for r in lines:
        r["moneyInTzs"], r["moneyOutTzs"] = round(r["moneyIn"], 2), round(r["moneyOut"], 2)
        r["moneyIn"], r["moneyOut"] = round(r.pop("nativeIn"), 2), round(r.pop("nativeOut"), 2)
        running = round(running + r["moneyIn"] - r["moneyOut"], 2)
        r["balance"] = running
        r["at"] = to_local(r["at"]).isoformat() if r["at"] else None
    return {"account": {"id": str(inst.id), "name": inst.name, "kind": inst.kind or "BANK",
                        "accountNo": inst.accountNo, "currencyType": (inst.currencyType or "TZS").upper()},
            "currency": (inst.currencyType or "TZS").upper(),
            "startDate": s, "endDate": e, "opening": opening, "closing": running,
            "moneyIn": round(sum(r["moneyIn"] for r in lines), 2),
            "moneyOut": round(sum(r["moneyOut"] for r in lines), 2), "lines": lines}


# ------------------------------------------------------------------ mapato mengine
def _income_rows(db: Session, rows: list[Income]) -> list[dict]:
    cats = {c.id: c.name for c in db.query(AccountCategory).all()}
    insts = {i.id: i.name for i in db.query(Institute).all()}
    offices = {o.id: o.name for o in db.query(Office).all()}
    users = _users(db, [r.logsId for r in rows])
    return [{"id": str(r.id), "details": r.details, "amount": r.amount, "currency": r.currency or "TZS",
             "amountOriginal": r.amountOriginal, "rate": r.rate,
             "category_id": str(r.category_id) if r.category_id else None, "category": cats.get(r.category_id),
             "institute_id": str(r.institute_id) if r.institute_id else None, "institute": insts.get(r.institute_id),
             "office_id": str(r.office_id) if r.office_id else None, "office": offices.get(r.office_id),
             "createdBy": users.get(r.logsId), "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


def incomes(db: Session, f: schema.IncomeSearch, user_id) -> list[dict]:
    q = db.query(Income).filter(Income.isBlocked.is_(False))
    start, end = day_range(f.startDate, f.endDate)
    if start is not None:
        q = q.filter(Income.created_at >= start)
    if end is not None:
        q = q.filter(Income.created_at < end)
    office = _scope(db, user_id, f.office_id)
    if office is not None:
        q = q.filter(Income.office_id == office)
    if f.category_id:
        q = q.filter(Income.category_id == to_uuid(f.category_id))
    if f.institute_id:
        q = q.filter(Income.institute_id == to_uuid(f.institute_id))
    return _income_rows(db, q.order_by(Income.created_at.desc()).limit(2000).all())


def save_income(db: Session, data: schema.IncomeSave, user_id, income_id=None) -> dict:
    from .locks import ensure_open

    ensure_open(db)
    if income_id is not None:
        old = db.get(Income, to_uuid(income_id))
        if old is not None:
            ensure_open(db, old.created_at)
    _category(db, data.category_id, "INCOME")
    if data.institute_id is not None:
        _account(db, data.institute_id)
    if data.office_id is not None and db.get(Office, data.office_id) is None:
        raise NotFound("Office not found")
    scope = office_scope(db, user_id)
    office_id = data.office_id
    if scope is not None:
        if office_id is not None and str(office_id) != str(scope):
            raise BadRequest("Unaweza kuandika mapato ya ofisi yako tu")
        office_id = scope
    code, rate = _rate(db, data.currency)
    local = rate == 1.0 and code in ("TZS", "TSH")
    fields = {"details": data.details.strip(), "amount": round(data.amount * rate, 2), "currency": code,
              "amountOriginal": None if local else data.amount, "rate": None if local else rate,
              "category_id": data.category_id, "institute_id": data.institute_id, "office_id": office_id}
    if income_id is None:
        row = Income(**fields, logsId=user_id)
        db.add(row)
    else:
        row = db.get(Income, to_uuid(income_id))
        if row is None or row.isBlocked:
            raise NotFound("Mapato hayapo")
        for k, v in fields.items():
            setattr(row, k, v)
    db.commit()
    note(f"Mapato mengine: {row.details} TSh {whole(row.amount)}")
    return _income_rows(db, [row])[0]


def delete_income(db: Session, income_id) -> bool:
    from .locks import ensure_open

    row = db.get(Income, to_uuid(income_id))
    if row is None:
        raise NotFound("Mapato hayapo")
    ensure_open(db, row.created_at)
    db.delete(row)
    db.commit()
    note(f"Mapato yamefutwa: {row.details} TSh {whole(row.amount)}")
    return True


# ------------------------------------------------------------------ uhamisho
def transfers(db: Session, start_date: str | None, end_date: str | None, account=None) -> list[dict]:
    q = db.query(Transfer).filter(Transfer.isBlocked.is_(False))
    start, end = day_range(start_date, end_date)
    if start is not None:
        q = q.filter(Transfer.created_at >= start)
    if end is not None:
        q = q.filter(Transfer.created_at < end)
    if account:
        a = to_uuid(account)
        q = q.filter((Transfer.from_id == a) | (Transfer.to_id == a))
    rows = q.order_by(Transfer.created_at.desc()).limit(2000).all()
    insts = {i.id: i for i in db.query(Institute).all()}
    names = {k: v.name for k, v in insts.items()}
    cur = {k: (v.currencyType or "TZS").upper() for k, v in insts.items()}
    users = _users(db, [r.logsId for r in rows])
    return [{"id": str(t.id), "from_id": str(t.from_id), "from": names.get(t.from_id), "to_id": str(t.to_id),
             "to": names.get(t.to_id), "amount": t.amount, "fromAmount": t.fromAmount, "toAmount": t.toAmount,
             "fromCurrency": cur.get(t.from_id, "TZS"), "toCurrency": cur.get(t.to_id, "TZS"),
             "note": t.note, "createdBy": users.get(t.logsId),
             "created_at": t.created_at.isoformat() if t.created_at else None} for t in rows]


def create_transfer(db: Session, data: schema.TransferSave, user_id) -> dict:
    from .locks import ensure_open

    ensure_open(db)
    if data.from_id == data.to_id:
        raise BadRequest("Chagua akaunti mbili tofauti")
    a, b = _account(db, data.from_id), _account(db, data.to_id)
    ra, rb = _acc_rate(db, a), _acc_rate(db, b)
    tzs = round(data.amount * ra, 2)
    same = (a.currencyType or "TZS").upper() == (b.currencyType or "TZS").upper() or (_local(a.currencyType) and _local(b.currencyType))
    to_amount = data.amount if same else (data.toAmount if data.toAmount and data.toAmount > 0 else round(tzs / rb, 2))
    t = Transfer(from_id=a.id, to_id=b.id, amount=tzs, fromAmount=round(data.amount, 2), toAmount=round(to_amount, 2),
                 note=(data.note or "").strip() or None, logsId=user_id)
    db.add(t)
    db.commit()
    note(f"Uhamisho {a.currencyType} {whole(data.amount)}: {a.name} -> {b.name} ({b.currencyType} {whole(to_amount)})")
    return {"id": str(t.id), "from_id": str(a.id), "from": a.name, "to_id": str(b.id), "to": b.name,
            "amount": t.amount, "fromAmount": t.fromAmount, "toAmount": t.toAmount, "note": t.note,
            "created_at": t.created_at.isoformat() if t.created_at else None}


def delete_transfer(db: Session, transfer_id) -> bool:
    from .locks import ensure_open

    t = db.get(Transfer, to_uuid(transfer_id))
    if t is None:
        raise NotFound("Uhamisho haupo")
    ensure_open(db, t.created_at)
    db.delete(t)
    db.commit()
    note(f"Uhamisho umefutwa (TSh {whole(t.amount)})")
    return True


# ------------------------------------------------------------------ mtaji na pesa za mmiliki
def _equity_rows(db: Session, rows) -> list[dict]:
    insts = {i.id: i.name for i in db.query(Institute).all()}
    users = _users(db, [r.logsId for r in rows])
    return [{"id": str(r.id), "kind": r.kind, "owner": r.owner, "details": r.details, "amount": r.amount,
             "currency": r.currency or "TZS", "amountOriginal": r.amountOriginal,
             "institute_id": str(r.institute_id) if r.institute_id else None, "institute": insts.get(r.institute_id),
             "createdBy": users.get(r.logsId), "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


def equity(db: Session, start_date: str | None = None, end_date: str | None = None) -> dict:
    from .model import Equity

    q = db.query(Equity).filter(Equity.isBlocked.is_(False))
    start, end = day_range(start_date, end_date)
    if start is not None:
        q = q.filter(Equity.created_at >= start)
    if end is not None:
        q = q.filter(Equity.created_at < end)
    rows = q.order_by(Equity.created_at.desc()).all()
    capital = sum(r.amount for r in rows if r.kind == "CAPITAL")
    drawings = sum(r.amount for r in rows if r.kind == "DRAWING")
    return {"items": _equity_rows(db, rows), "capital": round(capital, 2), "drawings": round(drawings, 2),
            "net": round(capital - drawings, 2)}


def save_equity(db: Session, data: schema.EquitySave, user_id) -> dict:
    from .locks import ensure_open
    from .model import EQUITY_KINDS, Equity

    ensure_open(db)
    kind = (data.kind or "CAPITAL").upper()
    if kind not in EQUITY_KINDS:
        raise BadRequest("Aina si sahihi (CAPITAL au DRAWING)")
    if data.institute_id is not None:
        _account(db, data.institute_id)
    code, rate = _rate(db, data.currency)
    local = _local(code) and rate == 1.0
    row = Equity(kind=kind, owner=(data.owner or "").strip() or None, details=(data.details or "").strip() or None,
                 amount=round(data.amount * rate, 2), currency=code, amountOriginal=None if local else data.amount,
                 rate=None if local else rate, institute_id=data.institute_id, logsId=user_id)
    db.add(row)
    db.commit()
    note(f"{'Mtaji umeingizwa' if kind == 'CAPITAL' else 'Mmiliki amechukua pesa'}: {code} {whole(data.amount)}"
         + (f" ({row.owner})" if row.owner else ""))
    return _equity_rows(db, [row])[0]


def delete_equity(db: Session, equity_id) -> bool:
    from .locks import ensure_open
    from .model import Equity

    row = db.get(Equity, to_uuid(equity_id))
    if row is None:
        raise NotFound("Rekodi haipo")
    ensure_open(db, row.created_at)
    db.delete(row)
    db.commit()
    note(f"Rekodi ya mtaji imefutwa (TSh {whole(row.amount)})")
    return True


# ------------------------------------------------------------------ kufunga mwezi
def locks(db: Session) -> list[dict]:
    from .model import PeriodLock

    rows = db.query(PeriodLock).order_by(PeriodLock.month.desc()).all()
    users = _users(db, [r.logsId for r in rows])
    return [{"id": str(r.id), "month": r.month, "note": r.note, "lockedBy": users.get(r.logsId),
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


def lock_month(db: Session, data: schema.LockSave, user_id) -> dict:
    import re

    from .model import PeriodLock

    month = (data.month or "").strip()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise BadRequest("Mwezi si sahihi (YYYY-MM)")
    if month > local_now().strftime("%Y-%m"):
        raise BadRequest("Huwezi kufunga mwezi ujao")
    if db.query(PeriodLock.id).filter(PeriodLock.month == month).first():
        raise Conflict("Mwezi huu umeshafungwa")
    db.add(PeriodLock(month=month, note=(data.note or "").strip() or None, logsId=user_id))
    db.commit()
    note(f"Mwezi {month} umefungwa (hesabu haziwezi kubadilishwa)")
    return next(r for r in locks(db) if r["month"] == month)


def unlock_month(db: Session, month: str) -> bool:
    from .model import PeriodLock

    row = db.query(PeriodLock).filter(PeriodLock.month == month).first()
    if row is None:
        raise NotFound("Mwezi huu haujafungwa")
    db.delete(row)
    db.commit()
    note(f"Mwezi {month} umefunguliwa")
    return True


# ------------------------------------------------------------------ faida na hasara
def _month(value: datetime | None) -> str:
    return to_local(value).strftime("%Y-%m") if value else "-"


def _months(s: str, e: str) -> list[str]:
    d, end = parse_date(s).replace(day=1), parse_date(e)
    out = []
    while d <= end:
        out.append(d.strftime("%Y-%m"))
        d = (d + timedelta(days=32)).replace(day=1)
    return out


def summary(db: Session, user_id, start_date: str | None = None, end_date: str | None = None, office=None) -> dict:
    from ..shipment.model import PackageCost

    start, end, s, e = _period(start_date, end_date)
    office = _scope(db, user_id, office)
    months = {m: {"month": m, "income": 0.0, "expenses": 0.0} for m in _months(s, e)}

    # 1. malipo ya ankara (pesa iliyopokelewa) - refund
    q = (db.query(Payment.paid, Payment.kind, Payment.created_at, Payment.institute_id)
         .join(Debt, Debt.id == Payment.debt_id).join(Invoice, Invoice.id == Debt.invoice_id)
         .filter(Payment.created_at >= start, Payment.created_at < end))
    if office is not None:
        q = q.filter(Invoice.office_id == office)
    paid = refunds = 0.0
    no_account = 0.0
    for amount, kind, at, inst in q.all():
        sign = -1 if kind == "REFUND" else 1
        if sign < 0:
            refunds += amount or 0
        else:
            paid += amount or 0
        if inst is None:
            no_account += sign * (amount or 0)
        months.setdefault(_month(at), {"month": _month(at), "income": 0.0, "expenses": 0.0})["income"] += sign * (amount or 0)

    # 2. mapato mengine
    cats = {c.id: c.name for c in db.query(AccountCategory).all()}
    q = db.query(Income).filter(Income.isBlocked.is_(False), Income.created_at >= start, Income.created_at < end)
    if office is not None:
        q = q.filter(Income.office_id == office)
    other: dict[str, float] = {}
    for x in q.all():
        key = cats.get(x.category_id, NO_CATEGORY)
        other[key] = other.get(key, 0) + (x.amount or 0)
        months.setdefault(_month(x.created_at), {"month": _month(x.created_at), "income": 0.0, "expenses": 0.0})["income"] += x.amount or 0

    # 3. matumizi yaliyoidhinishwa
    q = db.query(Expense).filter(approved_filter(), Expense.created_at >= start, Expense.created_at < end)
    if office is not None:
        q = q.filter(Expense.office_id == office)
    spent: dict[str, float] = {}
    for x in q.all():
        key = cats.get(x.category_id, NO_CATEGORY)
        spent[key] = spent.get(key, 0) + (x.amount or 0)
        months.setdefault(_month(x.created_at), {"month": _month(x.created_at), "income": 0.0, "expenses": 0.0})["expenses"] += x.amount or 0

    # 4. gharama za mabox (hazina ofisi - zinaonekana kwenye ripoti ya ofisi zote)
    box: dict[str, float] = {}
    if office is None:
        for c in (db.query(PackageCost)
                  .filter(PackageCost.created_at >= start, PackageCost.created_at < end).all()):
            box[c.category] = box.get(c.category, 0) + (c.amountTzs or 0)
            months.setdefault(_month(c.created_at), {"month": _month(c.created_at), "income": 0.0, "expenses": 0.0})["expenses"] += c.amountTzs or 0

    # inayosubiri idhini
    pq = db.query(func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0.0)).filter(Expense.status == "PENDING")
    if office is not None:
        pq = pq.filter(Expense.office_id == office)
    pending_count, pending_amount = pq.one()

    # madeni ya gharama tunayodaiwa (wakala / msafirishaji)
    from ..shipment.model import PackageCost

    owed = 0.0
    if office is None:
        for c in db.query(PackageCost).filter(PackageCost.payStatus.in_(("PARTIAL", "CREDIT"))).all():
            owed += c.owedTzs

    # madeni ya wateja (kwa taarifa)
    dq = db.query(func.coalesce(func.sum(Debt.debt), 0.0)).join(Invoice, Invoice.id == Debt.invoice_id).filter(Debt.debt > 0)
    if office is not None:
        dq = dq.filter(Invoice.office_id == office)

    # mali za kudumu: uchakavu (gharama) na faida/hasara ya kuuza mali (ofisi zote)
    depreciation = asset_gain = 0.0
    if office is None:
        from ..assets.service import depreciation_between, disposal_gain_between

        depreciation = depreciation_between(db, parse_date(s), parse_date(e))
        asset_gain = disposal_gain_between(db, parse_date(s), parse_date(e))
        if asset_gain:
            other["Faida/hasara ya kuuza mali"] = other.get("Faida/hasara ya kuuza mali", 0) + asset_gain

    invoice_income = paid - refunds
    other_total = sum(other.values())
    expenses_total = sum(spent.values())
    box_total = sum(box.values())
    income = invoice_income + other_total
    costs = expenses_total + box_total + depreciation
    profit = income - costs
    rows = sorted(months.values(), key=lambda r: r["month"])
    for r in rows:
        r["profit"] = round(r["income"] - r["expenses"], 2)
        r["income"], r["expenses"] = round(r["income"], 2), round(r["expenses"], 2)

    def items(d):
        return [{"name": k, "amount": round(v, 2)} for k, v in sorted(d.items(), key=lambda kv: -kv[1])]

    return {"startDate": s, "endDate": e, "office": str(office) if office else None,
            "invoicePayments": round(paid, 2), "refunds": round(refunds, 2), "invoiceIncome": round(invoice_income, 2),
            "otherIncome": round(other_total, 2), "otherIncomeByCategory": items(other),
            "income": round(income, 2),
            "expenses": round(expenses_total, 2), "expensesByCategory": items(spent),
            "boxCosts": round(box_total, 2), "boxCostsByCategory": items(box),
            "depreciation": round(depreciation, 2),
            "costs": round(costs, 2), "profit": round(profit, 2),
            "margin": round(profit / income * 100, 1) if income else 0.0,
            "pendingExpenses": int(pending_count or 0), "pendingAmount": round(float(pending_amount or 0), 2),
            "receivables": round(float(dq.scalar() or 0), 2), "payables": round(owed, 2),
            "paymentsWithoutAccount": round(no_account, 2),
            "months": rows}


_BOX_LABEL = {"FREIGHT": "Nauli", "CUSTOMS": "Ushuru", "CLEARING": "Clearing", "TRANSPORT": "Usafiri",
              "HANDLING": "Upakiaji", "OTHER": "Nyingine"}


def _office_name(db: Session, office) -> str:
    o = db.get(Office, office) if office else None
    return o.name if o else "Ofisi zote"


def summary_pdf(db: Session, user_id, start_date=None, end_date=None, office=None) -> tuple[bytes, str]:
    from ..core.report_pdf import ReportPdf, money

    d = summary(db, user_id, start_date, end_date, office)
    rep = ReportPdf("Faida na Hasara", _label(d["startDate"], d["endDate"]),
                    subtitle=_office_name(db, to_uuid(d["office"]) if d["office"] else None))
    rep.kpis([("Mapato (TSh)", money(d["income"])), ("Gharama (TSh)", money(d["costs"])),
              ("Faida (TSh)", money(d["profit"])), ("Asilimia", f"{d['margin']}%")])
    rep.section("Mapato")
    rows = [["Malipo ya ankara", d["invoicePayments"]], ["Pesa zilizorudishwa (refund)", -d["refunds"]]]
    rows += [[f"Mengine: {x['name']}", x["amount"]] for x in d["otherIncomeByCategory"]]
    rep.table(["Chanzo", "TSh"], rows, widths=[5, 2], money={1}, totals={1})
    rep.section("Matumizi")
    rep.table(["Kundi", "TSh"], [[x["name"], x["amount"]] for x in d["expensesByCategory"]],
              widths=[5, 2], money={1}, totals={1})
    if d["boxCostsByCategory"]:
        rep.section("Gharama za mabox (safari)")
        rep.table(["Aina", "TSh"], [[_BOX_LABEL.get(x["name"], x["name"]), x["amount"]] for x in d["boxCostsByCategory"]],
                  widths=[5, 2], money={1}, totals={1})
    if d.get("depreciation"):
        rep.note(f"Uchakavu wa mali za kudumu (umejumuishwa kwenye gharama): TSh {whole(d['depreciation'])}")
    if len(d["months"]) > 1:
        rep.bars("Kwa mwezi", [m["month"] for m in d["months"]],
                 [("Mapato", [m["income"] for m in d["months"]]), ("Gharama", [m["expenses"] for m in d["months"]])])
        rep.table(["Mwezi", "Mapato", "Gharama", "Faida"],
                  [[m["month"], m["income"], m["expenses"], m["profit"]] for m in d["months"]],
                  widths=[2, 2, 2, 2], money={1, 2, 3}, totals={1, 2, 3})
    if d["pendingExpenses"]:
        rep.note(f"Tahadhari: matumizi {d['pendingExpenses']} (TSh {whole(d['pendingAmount'])}) yanasubiri idhini "
                 "na hayajahesabiwa.")
    rep.note(f"Madeni ya wateja ambayo hayajalipwa: TSh {whole(d['receivables'])}")
    if d["payables"]:
        rep.note(f"Madeni ya gharama tunayodaiwa (wakala / msafirishaji): TSh {whole(d['payables'])}")
    return rep.build(), f"faida_hasara_{d['startDate']}_{d['endDate']}"


def summary_excel(db: Session, user_id, start_date=None, end_date=None, office=None) -> tuple[bytes, str]:
    from ..core import excel

    d = summary(db, user_id, start_date, end_date, office)
    label = f"{_label(d['startDate'], d['endDate'])} - {_office_name(db, to_uuid(d['office']) if d['office'] else None)}"
    rows = [["MAPATO", "Malipo ya ankara", d["invoicePayments"]],
            ["MAPATO", "Pesa zilizorudishwa (refund)", -d["refunds"]]]
    rows += [["MAPATO", f"Mengine: {x['name']}", x["amount"]] for x in d["otherIncomeByCategory"]]
    rows += [["MATUMIZI", x["name"], -x["amount"]] for x in d["expensesByCategory"]]
    rows += [["GHARAMA ZA MABOX", _BOX_LABEL.get(x["name"], x["name"]), -x["amount"]] for x in d["boxCostsByCategory"]]
    if d.get("depreciation"):
        rows.append(["UCHAKAVU", "Uchakavu wa mali za kudumu", -d["depreciation"]])
    sheets = [excel.Sheet("Faida na Hasara", ["Sehemu", "Maelezo", "TSh"], rows, money={2}, totals={2}, subtitle=label),
              excel.Sheet("Kwa mwezi", ["Mwezi", "Mapato", "Gharama", "Faida"],
                          [[m["month"], m["income"], m["expenses"], m["profit"]] for m in d["months"]],
                          money={1, 2, 3}, totals={1, 2, 3}, subtitle=label)]
    acc = accounts(db, user_id)
    sheets.append(excel.Sheet("Salio la akaunti", ["Akaunti", "Aina", "Namba", "Ofisi", "Salio (TSh)"],
                              [[a["name"], KIND_LABEL.get(a["kind"], a["kind"]), a["accountNo"], a["office"] or "",
                                a["balance"]] for a in acc["items"]], money={4}, totals={4}))
    return excel.build(sheets), f"faida_hasara_{d['startDate']}_{d['endDate']}"


def statement_excel(db: Session, account_id, start_date=None, end_date=None) -> tuple[bytes, str]:
    from ..core import excel

    d = statement(db, account_id, start_date, end_date)
    rows = [[None, "SALIO LA KUANZIA", "", 0, 0, d["opening"]]]
    rows += [[datetime.fromisoformat(r["at"]) if r["at"] else None, r["details"], r["ref"], r["moneyIn"],
              r["moneyOut"], r["balance"]] for r in d["lines"]]
    sheet = excel.Sheet(d["account"]["name"][:31], ["Muda", "Maelezo", "Kumb.", "Imeingia", "Imetoka", "Salio"], rows,
                        money={3, 4, 5}, subtitle=f"{_label(d['startDate'], d['endDate'])} - "
                                                  f"salio la kufunga TSh {whole(d['closing'])}")
    return excel.build([sheet]), f"akaunti_{d['startDate']}_{d['endDate']}"


# ------------------------------------------------------------------ madeni tunayodaiwa (yote)
def payables(db: Session) -> dict:
    """Madeni ya gharama za mabox + matumizi yaliyoidhinishwa ambayo hayajalipwa yote."""
    from ..shipment import service as shipment

    box = shipment.payables(db)
    items = [{**i, "source": "BOX_COST", "title": f"Box {i['boxId']} · {_BOX_LABEL.get(i['category'], i['category'])}"}
             for i in box["items"]]
    for e in (db.query(Expense).filter(approved_filter(), Expense.payStatus.in_(("PARTIAL", "CREDIT")))
              .order_by(Expense.created_at).all()):
        if e.owedTzs <= 0:
            continue
        items.append({"id": str(e.id), "source": "EXPENSE", "title": e.details, "category": None,
                      "amountTzs": e.amount, "paidTzs": e.paidTzs or 0, "owedTzs": e.owedTzs,
                      "payStatus": e.payStatus, "supplier": e.supplier, "note": None,
                      "created_at": e.created_at.isoformat() if e.created_at else None})
    groups: dict[str, dict] = {}
    for i in items:
        g = groups.setdefault(i["supplier"] or "-", {"supplier": i["supplier"] or "-", "owed": 0.0, "count": 0})
        g["owed"] = round(g["owed"] + i["owedTzs"], 2)
        g["count"] += 1
    return {"items": items, "total": round(sum(i["owedTzs"] for i in items), 2),
            "bySupplier": sorted(groups.values(), key=lambda x: -x["owed"])}


# ------------------------------------------------------------------ mizania (balance sheet)
def balance_sheet(db: Session, user_id) -> dict:
    """
    Mizania ya leo (mfumo wa kuingiza mara moja - single entry):
        MALI     = salio la akaunti (TSh) + madeni ya wateja + mali za kudumu (thamani baada ya uchakavu)
        MADENI   = madeni ya gharama za mabox + madeni ya matumizi
        MTAJI    = mtaji ulioingizwa - pesa za mmiliki + faida iliyolimbikizwa (inayokamilisha mizania)
    """
    acc = accounts(db, None)
    receivables = float(db.query(func.coalesce(func.sum(Debt.debt), 0.0)).filter(Debt.debt > 0).scalar() or 0)
    from ..assets.service import book_value_total

    fixed = book_value_total(db)
    pay = payables(db)
    box_owed = sum(i["owedTzs"] for i in pay["items"] if i["source"] == "BOX_COST")
    exp_owed = sum(i["owedTzs"] for i in pay["items"] if i["source"] == "EXPENSE")
    extra_liab: list[dict] = []
    eq = equity(db)
    assets_total = acc["total"] + receivables + fixed
    liab_total = box_owed + exp_owed + sum(x["amount"] for x in extra_liab)
    net = assets_total - liab_total
    retained = net - eq["capital"] + eq["drawings"]
    return {
        "date": local_now().date().isoformat(),
        "assets": {"accounts": [{"name": a["name"], "currency": a["currencyType"], "native": a["nativeBalance"],
                                 "amount": a["balance"]} for a in acc["items"]],
                   "cash": acc["total"], "receivables": round(receivables, 2), "fixedAssets": round(fixed, 2),
                   "total": round(assets_total, 2)},
        "liabilities": {"boxCosts": round(box_owed, 2), "expenses": round(exp_owed, 2), "other": extra_liab,
                        "total": round(liab_total, 2)},
        "equity": {"capital": eq["capital"], "drawings": eq["drawings"], "retained": round(retained, 2),
                   "total": round(net, 2)},
    }
