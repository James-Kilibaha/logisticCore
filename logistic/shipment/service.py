"""
Gharama za kusafirisha kila box/kontena na faida yake.

    mapato  = jumla ya `unitPrice` ya mizigo ndani ya box (+ gharama za stoo za ankara zake, zikiwekwa)
    faida   = mapato - gharama za box (nauli, ushuru, clearing, ...)
"""
from sqlalchemy.orm import Session

from ..core.audit import note
from ..core.exceptions import BadRequest, NotFound
from ..core.utils import day_range, product_cbm, split_ids, whole
from ..package.dao import PackageDao
from ..package.model import Package
from ..payment import storage
from ..payment.model import Debt
from ..product.model import Product
from . import schema
from .model import CostPayment, PackageCost


def _package(db: Session, package_id) -> Package:
    package = PackageDao(db).get(package_id)
    if package is None:
        raise NotFound("Package not found")
    return package


def _rate(db: Session, currency: str) -> tuple[str, float]:
    code = (currency or "TZS").strip().upper() or "TZS"
    rate = storage.currency_rate(db, code)
    if not rate:
        raise BadRequest(f"No exchange rate for {code}. Add it in Settings first")
    return code, rate


def _check_account(db: Session, institute_id) -> None:
    if institute_id is None:
        return
    from ..settings.institute.model import Institute

    inst = db.get(Institute, institute_id)
    if inst is None or inst.isBlocked:
        raise BadRequest("Akaunti ya fedha haipo")


def _set_status(cost: PackageCost) -> None:
    owed = cost.owedTzs
    if owed <= 0.009:
        cost.payStatus = "PAID"
    elif (cost.paidTzs or 0) <= 0.009:
        cost.payStatus = "CREDIT"
    else:
        cost.payStatus = "PARTIAL"


def add_cost(db: Session, package_id, data: schema.CostCreate, user_id, commit: bool = True) -> PackageCost:
    from ..accounting.locks import ensure_open

    ensure_open(db)
    package = _package(db, package_id)
    currency, rate = _rate(db, data.currency)
    supplier = (data.supplier or "").strip() or None
    if data.payStatus in ("PARTIAL", "CREDIT") and not supplier:
        raise BadRequest("Weka jina la tunayemdai (wakala / msafirishaji) kwa gharama ya deni")
    if data.payStatus == "PARTIAL" and not (data.paidAmount and 0 < data.paidAmount < data.amount):
        raise BadRequest("Kiasi kilicholipwa kiwe zaidi ya 0 na chini ya gharama yote")
    _check_account(db, data.institute_id)
    amount_tzs = round(data.amount * rate, 2)
    paid = {"PAID": data.amount, "PARTIAL": data.paidAmount or 0, "CREDIT": 0.0}[data.payStatus]
    paid_tzs = round(paid * rate, 2)
    cost = PackageCost(package_id=package.id, category=data.category, amount=data.amount, currency=currency,
                       rate=rate, amountTzs=amount_tzs, note=(data.note or "").strip() or None,
                       supplier=supplier, paidTzs=paid_tzs, logsId=user_id)
    _set_status(cost)
    db.add(cost)
    db.flush()
    if paid_tzs > 0:
        local = currency in ("TZS", "TSH") and rate == 1.0
        db.add(CostPayment(cost_id=cost.id, amount=paid_tzs, currency=currency,
                           amountOriginal=None if local else paid, rate=None if local else rate,
                           institute_id=data.institute_id, note="Malipo ya mwanzo", logsId=user_id))
    if not commit:
        return cost
    db.commit()
    db.refresh(cost)
    owed = f", deni TSh {whole(cost.owedTzs)} kwa {supplier}" if cost.owedTzs else ""
    note(f"Box {package.boxId}: gharama {data.category} {currency} {data.amount:,.2f} (TSh {whole(cost.amountTzs)}){owed}")
    from ..demand.service import refresh_package

    refresh_package(db, package.id)  # dai la gharama za box hili linajifunga likikamilika
    return cost


def costs(db: Session, package_id) -> list[PackageCost]:
    _package(db, package_id)
    return (db.query(PackageCost).filter(PackageCost.package_id == package_id)
            .order_by(PackageCost.created_at).all())


def _cost(db: Session, cost_id) -> PackageCost:
    from ..core.dao import to_uuid

    cost = db.query(PackageCost).filter(PackageCost.id == to_uuid(cost_id)).one_or_none()
    if cost is None:
        raise NotFound("Cost not found")
    return cost


def delete_cost(db: Session, cost_id) -> bool:
    from ..accounting.locks import ensure_open

    cost = _cost(db, cost_id)
    ensure_open(db, cost.created_at)
    db.delete(cost)
    db.commit()
    note(f"Gharama ya box imefutwa ({cost.category} TSh {whole(cost.amountTzs)})")
    return True


def pay_cost(db: Session, cost_id, data: schema.CostPay, user_id) -> PackageCost:
    """Kulipa deni la gharama (lote au sehemu) kutoka kwenye akaunti ya fedha."""
    from ..accounting.locks import ensure_open

    ensure_open(db)
    cost = _cost(db, cost_id)
    owed = cost.owedTzs
    if owed <= 0:
        raise BadRequest("Gharama hii haina deni")
    currency, rate = _rate(db, data.currency)
    _check_account(db, data.institute_id)
    amount_tzs = round(data.amount * rate, 2)
    if amount_tzs > owed + 1:
        raise BadRequest(f"Kiasi kinazidi deni (TSh {whole(owed)})")
    amount_tzs = min(amount_tzs, owed)
    local = currency in ("TZS", "TSH") and rate == 1.0
    db.add(CostPayment(cost_id=cost.id, amount=amount_tzs, currency=currency,
                       amountOriginal=None if local else data.amount, rate=None if local else rate,
                       institute_id=data.institute_id, note=(data.note or "").strip() or None, logsId=user_id))
    cost.paidTzs = round((cost.paidTzs or 0) + amount_tzs, 2)
    _set_status(cost)
    db.commit()
    db.refresh(cost)
    package = db.get(Package, cost.package_id)
    note(f"Deni la gharama limelipwa: Box {package.boxId if package else ''} {cost.supplier or ''} "
         f"TSh {whole(amount_tzs)} (limebaki TSh {whole(cost.owedTzs)})")
    return cost


def cost_payments(db: Session, cost_id) -> list[dict]:
    from ..settings.institute.model import Institute

    cost = _cost(db, cost_id)
    rows = (db.query(CostPayment).filter(CostPayment.cost_id == cost.id).order_by(CostPayment.created_at).all())
    names = {i.id: i.name for i in db.query(Institute).all()}
    return [{"id": str(r.id), "amount": r.amount, "currency": r.currency, "amountOriginal": r.amountOriginal,
             "institute": names.get(r.institute_id), "note": r.note,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


def payables(db: Session, supplier: str | None = None, include_paid: bool = False) -> dict:
    """Madeni ya gharama tunayodaiwa (wakala, msafirishaji ...), kwa kila gharama na kwa kila mdai."""
    q = db.query(PackageCost, Package.boxId, Package.trackNumber).join(Package, Package.id == PackageCost.package_id)
    if include_paid:
        q = q.filter(PackageCost.payStatus.isnot(None))
    else:
        q = q.filter(PackageCost.payStatus.in_(("PARTIAL", "CREDIT")))
    if supplier:
        q = q.filter(PackageCost.supplier == supplier)
    rows = []
    by_supplier: dict[str, dict] = {}
    for c, box, track in q.order_by(PackageCost.created_at).all():
        rows.append({"id": str(c.id), "package_id": str(c.package_id), "boxId": box, "trackNumber": track,
                     "category": c.category, "amount": c.amount, "currency": c.currency, "amountTzs": c.amountTzs,
                     "paidTzs": c.paidTzs or 0, "owedTzs": c.owedTzs, "payStatus": c.payStatus,
                     "supplier": c.supplier, "note": c.note,
                     "created_at": c.created_at.isoformat() if c.created_at else None})
        s = by_supplier.setdefault(c.supplier or "-", {"supplier": c.supplier or "-", "owed": 0.0, "count": 0})
        s["owed"] = round(s["owed"] + c.owedTzs, 2)
        s["count"] += 1
    return {"items": rows, "total": round(sum(r["owedTzs"] for r in rows), 2),
            "bySupplier": sorted(by_supplier.values(), key=lambda x: -x["owed"])}


def all_costs(db: Session, start_date: str | None = None, end_date: str | None = None, category: str | None = None,
              pay_status: str | None = None, user_id=None, box: str | None = None) -> dict:
    """Gharama zote za mabox kwa kipindi (mhasibu), au alizojaza mtumiaji mmoja (`user_id`)."""
    from ..core.dao import to_uuid
    from ..user.model import User

    q = (db.query(PackageCost, Package.boxId, Package.trackNumber)
         .join(Package, Package.id == PackageCost.package_id))
    start, end = day_range(start_date, end_date)
    if start is not None:
        q = q.filter(PackageCost.created_at >= start)
    if end is not None:
        q = q.filter(PackageCost.created_at < end)
    if category:
        q = q.filter(PackageCost.category == category.upper())
    if pay_status:
        status = pay_status.upper()
        q = q.filter((PackageCost.payStatus == "PAID") | PackageCost.payStatus.is_(None)) if status == "PAID" \
            else q.filter(PackageCost.payStatus == status)
    if user_id is not None:
        q = q.filter(PackageCost.logsId == to_uuid(user_id))
    if box:
        q = q.filter(Package.boxId.ilike(f"%{box.strip()}%"))
    rows = q.order_by(PackageCost.created_at.desc()).limit(3000).all()
    ids = {c.logsId for c, _, _ in rows if c.logsId}
    users = {u.id: (f"{u.firstName or ''} {u.lastName or ''}".strip() or u.username)
             for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    items, by_cat = [], {}
    for c, box_id, track in rows:
        paid = c.amountTzs if c.paidTzs is None else (c.paidTzs or 0)
        items.append({"id": str(c.id), "package_id": str(c.package_id), "boxId": box_id, "trackNumber": track,
                      "category": c.category, "amount": c.amount, "currency": c.currency, "rate": c.rate,
                      "amountTzs": c.amountTzs, "paidTzs": round(paid, 2), "owedTzs": c.owedTzs,
                      "payStatus": c.payStatus or "PAID", "supplier": c.supplier, "note": c.note,
                      "createdBy": users.get(c.logsId), "created_at": c.created_at.isoformat() if c.created_at else None})
        by_cat[c.category] = round(by_cat.get(c.category, 0) + (c.amountTzs or 0), 2)
    return {"items": items, "total": round(sum(i["amountTzs"] for i in items), 2),
            "paid": round(sum(i["paidTzs"] for i in items), 2), "owed": round(sum(i["owedTzs"] for i in items), 2),
            "boxes": len({i["package_id"] for i in items}), "byCategory": by_cat}


def box_kg(db: Session, package: Package) -> float:
    return _profit(db, package).kg


def _box_expenses(db: Session, package_ids) -> dict:
    """Matumizi ya ofisi yaliyoidhinishwa na kufungwa kwenye box (uhasibu) - {package_id: TSh}."""
    from sqlalchemy import func

    from ..expense.dao import approved_filter
    from ..expense.model import Expense

    ids = [i for i in package_ids if i]
    if not ids:
        return {}
    rows = (db.query(Expense.package_id, func.coalesce(func.sum(Expense.amount), 0.0))
            .filter(Expense.package_id.in_(ids), approved_filter()).group_by(Expense.package_id).all())
    return {pid: float(total or 0) for pid, total in rows}


def _profit(db: Session, package: Package, cost_rows: list[PackageCost] | None = None,
            expenses: float | None = None) -> schema.Profit:
    product_ids = split_ids(package.productList)
    products = db.query(Product).filter(Product.id.in_(product_ids)).all() if product_ids else []
    invoice_ids = {p.invoice_id for p in products}
    revenue = sum(p.unitPrice or 0 for p in products)
    storage_charges = 0.0
    if invoice_ids:
        storage_charges = sum(d.storageCharge or 0 for d in db.query(Debt).filter(Debt.invoice_id.in_(invoice_ids)))
    if cost_rows is None:
        cost_rows = db.query(PackageCost).filter(PackageCost.package_id == package.id).all()
    by_category: dict[str, float] = {}
    for c in cost_rows:
        by_category[c.category] = by_category.get(c.category, 0) + (c.amountTzs or 0)
    if expenses is None:
        expenses = _box_expenses(db, [package.id]).get(package.id, 0.0)
    if expenses:
        by_category["EXPENSE"] = by_category.get("EXPENSE", 0) + expenses
    total_costs = sum(by_category.values())
    kg = sum(p.weight or 0 for p in products)
    income = revenue + storage_charges
    profit = income - total_costs
    return schema.Profit(
        packageId=package.id, boxId=package.boxId, packageType=package.packageType,
        trackNumber=package.trackNumber or None, closedAt=package.update_at if package.isBoxClose else None,
        items=len(products), invoices=len(invoice_ids), kg=round(kg, 2),
        cbm=round(sum(product_cbm(p) for p in products), 3), revenue=round(revenue, 2),
        storageCharges=round(storage_charges, 2), costs=round(total_costs, 2), profit=round(profit, 2),
        margin=round(profit / income * 100, 1) if income else 0.0,
        costPerKg=round(total_costs / kg, 2) if kg else 0.0, byCategory=by_category)


def profit(db: Session, package_id) -> schema.Profit:
    return _profit(db, _package(db, package_id))


def profit_report(db: Session, start_date: str | None, end_date: str | None) -> schema.ProfitReport:
    """Mabox yaliyofungwa (kusafirishwa) ndani ya kipindi."""
    start, end = day_range(start_date, end_date)
    q = db.query(Package).filter(Package.isBoxClose.is_(True))
    if start:
        q = q.filter(Package.update_at >= start)
    if end:
        q = q.filter(Package.update_at < end)
    packages = q.order_by(Package.update_at.desc()).all()
    costs_by_pkg: dict = {}
    if packages:
        for c in db.query(PackageCost).filter(PackageCost.package_id.in_([p.id for p in packages])):
            costs_by_pkg.setdefault(c.package_id, []).append(c)
    spent = _box_expenses(db, [p.id for p in packages])
    rows = [_profit(db, p, costs_by_pkg.get(p.id, []), spent.get(p.id, 0.0)) for p in packages]
    revenue = sum(r.revenue + r.storageCharges for r in rows)
    total_costs = sum(r.costs for r in rows)
    by_carrier: dict[str, dict[str, float]] = {}
    for r in rows:
        k = "SEA" if (r.packageType or "").upper() == "SEA" else "AIR"
        agg = by_carrier.setdefault(k, {"boxes": 0, "revenue": 0.0, "costs": 0.0, "profit": 0.0, "kg": 0.0})
        agg["boxes"] += 1
        agg["revenue"] += r.revenue + r.storageCharges
        agg["costs"] += r.costs
        agg["profit"] += r.profit
        agg["kg"] += r.kg
    profit_total = revenue - total_costs
    return schema.ProfitReport(rows=rows, revenue=round(revenue, 2), costs=round(total_costs, 2),
                               profit=round(profit_total, 2),
                               margin=round(profit_total / revenue * 100, 1) if revenue else 0.0,
                               byCarrier=by_carrier)
