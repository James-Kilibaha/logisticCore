"""
Ripoti zote za PDF (reportlab) - za zamani zimeboreshwa na mpya zimeongezwa.

Aina (kind):
    revenue      Mapato kwa hali ya deni (zamani: "range")
    debt         Madeni (hali + umri)
    cargo        Mizigo iliyopokelewa (zamani: "product")
    income       Malipo kwa benki / njia, mfanyakazi na siku (zamani: "financial-income")
    expenditure  Matumizi kwa ofisi
    summary      Muhtasari wa biashara (mpya): kwa mwezi, usafiri, njia za malipo
    customers    Wateja bora (mpya)
    boxes        Mabox yaliyosafirishwa na faida (mpya)
    storage      Mapato ya stoo na mizigo iliyochelewa (mpya)
    handovers    Mizigo iliyokabidhiwa (mpya)
    aging        Madeni kwa umri (mpya kama PDF)
    statement    Taarifa ya mteja mmoja (mpya, inahitaji customerId)
"""
from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from ..core.enums import EInvoiceStatus, EPaymentKind, EPaymentStatus
from ..core.exceptions import BadRequest
from ..core.report_pdf import ReportPdf, money, num
from ..core.utils import day_range, local_now, parse_date, product_cbm, to_local
from ..customer.model import Customer
from ..expense.model import Expense
from ..invoice.model import Invoice
from ..payment.model import Debt, Payment
from ..settings.institute.model import Institute
from ..user.model import User

KINDS = ("revenue", "debt", "cargo", "income", "expenditure", "summary", "customers", "boxes", "storage",
         "handovers", "aging", "statement")
_DEAD = (EInvoiceStatus.BLOCKED.name, EInvoiceStatus.BLOCK.name)
_PAY = {"PAID": "Zimelipwa", "DEBT": "Zinadaiwa (sehemu)", "OPEN": "Hazijalipwa"}


class Params(BaseModel):
    startDate: str | None = None
    endDate: str | None = None
    status: str | None = None       # hali ya deni (PAID / DEBT / OPEN)
    office: str | None = None       # ofisi
    customerId: str | None = None   # statement
    carrier: str | None = None      # AIR / SEA


def _period(p: Params, required: bool = True) -> tuple[datetime | None, datetime | None, str]:
    if required and not (p.startDate and p.endDate):
        # chaguo-msingi: mwezi huu
        today = local_now().date()
        p = p.model_copy(update={"startDate": p.startDate or today.replace(day=1).isoformat(),
                                 "endDate": p.endDate or today.isoformat()})
    start, end = day_range(p.startDate, p.endDate)
    if start and end and start >= end:
        raise BadRequest("startDate must be before endDate")
    s, e = parse_date(p.startDate), parse_date(p.endDate)
    label = f"{s:%d/%m/%Y} - {e:%d/%m/%Y}" if s and e else (f"Hadi {local_now():%d/%m/%Y}")
    return start, end, label


def _d(v) -> str:
    return f"{to_local(v):%d/%m/%Y}" if v else "-"


def _office(q, p: Params, col=Invoice.office_id):
    from ..core.dao import to_uuid

    if p.office and to_uuid(p.office):
        q = q.filter(or_(col == to_uuid(p.office), col.is_(None)))
    return q


def _carrier_name(c: str | None) -> str:
    return {"AIR": "Ndege", "SEA": "Meli"}.get((c or "").upper(), c or "-")


def _debts(db: Session, p: Params, start, end, status: str | None = None):
    q = (db.query(Debt, Invoice).join(Invoice, Invoice.id == Debt.invoice_id)
         .options(selectinload(Invoice.customer), selectinload(Invoice.product))
         .filter(Invoice.status.notin_(_DEAD)))
    if start is not None:
        q = q.filter(Debt.created_at >= start)
    if end is not None:
        q = q.filter(Debt.created_at < end)
    if status:
        q = q.filter(Debt.status == status)
    return _office(q, p).order_by(Debt.created_at).all()


def _billed(d: Debt) -> float:
    return (d.amount or 0) + (d.storageCharge or 0) - (d.discount or 0)


def _payments(db: Session, p: Params, start, end):
    q = (db.query(Payment, Debt, Invoice, Institute, User)
         .join(Debt, Debt.id == Payment.debt_id).join(Invoice, Invoice.id == Debt.invoice_id)
         .outerjoin(Institute, Institute.id == Payment.institute_id).outerjoin(User, User.id == Payment.logsId)
         .options(selectinload(Invoice.customer)))
    if start is not None:
        q = q.filter(Payment.created_at >= start)
    if end is not None:
        q = q.filter(Payment.created_at < end)
    return _office(q, p).order_by(Payment.created_at).all()


def _signed(pay: Payment) -> float:
    return (pay.paid or 0) * (-1 if pay.kind == EPaymentKind.REFUND.name else 1)


# ===================================================================== ripoti
def revenue(db, p: Params) -> bytes:
    start, end, label = _period(p)
    status = (p.status or "PAID").upper()
    rows = _debts(db, p, start, end, status)
    rep = ReportPdf("Ripoti ya mapato", label, wide=True, subtitle=_PAY.get(status, status))
    data, by_carrier = [], {}
    for d, inv in rows:
        c = inv.customer[0] if inv.customer else None
        kg = sum(x.weight or 0 for x in inv.product)
        for x in inv.product:
            by_carrier[_carrier_name(x.carrierType)] = by_carrier.get(_carrier_name(x.carrierType), 0) + (x.weight or 0)
        data.append([_d(d.created_at), inv.invoiceNumber, c.name if c else "-",
                     ", ".join(x.description for x in inv.product)[:70], kg,
                     sum(x.quantities or 0 for x in inv.product), _billed(d), d.paid or 0, max(d.debt or 0, 0)])
    rep.kpis([("Ankara", num(len(data))), ("Jumla iliyotozwa (TSh)", money(sum(r[6] for r in data))),
              ("Imelipwa (TSh)", money(sum(r[7] for r in data))), ("Baki (TSh)", money(sum(r[8] for r in data)))])
    rep.pie("Kilo kwa usafiri", list(by_carrier.items()), value_fmt=lambda v: f"{num(v)} kg")
    rep.table(["Tarehe", "Ankara", "Mteja", "Mizigo", "Kg", "Katoni", "Iliyotozwa", "Imelipwa", "Baki"], data,
              widths=[1, 1, 2, 3.5, 0.8, 0.8, 1.3, 1.3, 1.2], numbers={4, 5}, money={6, 7, 8},
              totals={4, 5, 6, 7, 8})
    return rep.build()


def debt(db, p: Params) -> bytes:
    from .analytics import BUCKETS, aging as aging_data

    data = aging_data(db)
    items = data["invoices"]
    rep = ReportPdf("Ripoti ya madeni", f"Hadi {local_now():%d/%m/%Y}", wide=True)
    rep.kpis([("Ankara zinazodaiwa", num(len(items))), ("Jumla ya deni (TSh)", money(data["total"])),
              ("Wateja wanaodaiwa", num(len(data["customers"]))),
              ("Zaidi ya siku 60 (TSh)", money(data["totals"].get("60+", 0)))])
    rep.pie("Madeni kwa umri (siku)", [(f"Siku {b}", data["totals"].get(b, 0)) for b in BUCKETS])
    rep.section("Kwa ankara")
    rep.table(["Ankara", "Mteja", "Simu", "Hali", "Siku", "Jumla", "Imelipwa", "Deni"],
              [[r["invoiceNumber"], r["customerName"], r["phone"] or "-", r["status"], r["days"], r["total"],
                r["paid"], r["balance"]] for r in items],
              widths=[1, 2.2, 1.6, 1.2, 0.6, 1.3, 1.3, 1.3], numbers={4}, money={5, 6, 7}, totals={5, 6, 7})
    rep.section("Kwa mteja")
    rep.table(["Mteja", "Simu", "Ankara", "Siku (ya zamani)", *[f"Siku {b}" for b in BUCKETS], "Jumla"],
              [[r["customerName"], r["phone"] or "-", r["invoices"], r["oldestDays"], *[r[b] for b in BUCKETS],
                r["total"]] for r in data["customers"]],
              widths=[2.2, 1.6, 0.7, 1, 1.1, 1.1, 1.1, 1.1, 1.3], numbers={2, 3}, money={4, 5, 6, 7, 8},
              totals={2, 4, 5, 6, 7, 8})
    return rep.build()


def cargo(db, p: Params) -> bytes:
    start, end, label = _period(p)
    q = (db.query(Invoice).options(selectinload(Invoice.customer), selectinload(Invoice.product))
         .filter(Invoice.status.notin_(_DEAD)))
    if start:
        q = q.filter(Invoice.created_at >= start)
    if end:
        q = q.filter(Invoice.created_at < end)
    invoices = _office(q, p).order_by(Invoice.created_at).all()
    rows, by_carrier, by_desc = [], {}, {}
    for inv in invoices:
        c = inv.customer[0] if inv.customer else None
        for x in inv.product:
            if p.carrier and (x.carrierType or "").upper() != p.carrier.upper():
                continue
            name = _carrier_name(x.carrierType)
            agg = by_carrier.setdefault(name, [0.0, 0.0])
            agg[0] += x.weight or 0
            agg[1] += x.quantities or 0
            key = (x.description or "-").strip().title()
            by_desc[key] = by_desc.get(key, 0) + (x.weight or 0)
            rows.append([_d(inv.created_at), inv.invoiceNumber, c.name if c else "-", x.description, x.trackNumber or "-",
                         name, x.quantities or 0, x.weight or 0, round(product_cbm(x), 3), x.unitPrice or 0])
    rep = ReportPdf("Ripoti ya mizigo", label, wide=True, subtitle=_carrier_name(p.carrier) if p.carrier else None)
    rep.kpis([("Ankara", num(len({r[1] for r in rows}))), ("Mizigo", num(len(rows))),
              ("Katoni", num(sum(r[6] for r in rows))), ("Kilo", num(sum(r[7] for r in rows))),
              ("CBM", num(sum(r[8] for r in rows), 3)), ("Thamani (TSh)", money(sum(r[9] for r in rows)))], per_row=6)
    rep.pie("Kilo kwa usafiri", [(k, v[0]) for k, v in by_carrier.items()], value_fmt=lambda v: f"{num(v)} kg")
    top = sorted(by_desc.items(), key=lambda kv: -kv[1])
    rep.pie("Aina za mizigo (kg) - 8 za juu", top[:8] + ([("Nyingine", sum(v for _, v in top[8:]))] if top[8:] else []),
            value_fmt=lambda v: f"{num(v)} kg")
    rep.table(["Tarehe", "Ankara", "Mteja", "Mzigo", "Track", "Usafiri", "Katoni", "Kg", "CBM", "Thamani"], rows,
              widths=[1, 1, 2, 2.4, 1.6, 0.8, 0.8, 0.8, 0.8, 1.2], numbers={6, 7, 8}, money={9},
              totals={6, 7, 8, 9})
    return rep.build()


def income(db, p: Params) -> bytes:
    start, end, label = _period(p)
    rows = _payments(db, p, start, end)
    by_inst, by_staff, by_day = {}, {}, {}
    detail = []
    for pay, _debt, inv, inst, user in rows:
        amount = _signed(pay)
        iname = f"{inst.name} [{inst.currencyType}]" if inst else "Haijulikani"
        sname = f"{user.firstName} {user.lastName}" if user else "-"
        day = _d(pay.created_at)
        by_inst[iname] = by_inst.get(iname, 0) + amount
        by_staff[sname] = by_staff.get(sname, 0) + amount
        by_day[day] = by_day.get(day, 0) + amount
        c = inv.customer[0] if inv.customer else None
        detail.append([f"{to_local(pay.created_at):%d/%m/%Y %H:%M}" if pay.created_at else "-", pay.receiptNumber or "-",
                       inv.invoiceNumber, c.name if c else "-", "Refund" if amount < 0 else "Malipo", iname,
                       pay.currency or "TZS", amount, sname])
    from ..payment.storage import storage_income

    split = storage_income(db, start, end)
    rep = ReportPdf("Ripoti ya mapato kwa njia za malipo", label, wide=True)
    rep.kpis([("Malipo yote (TSh)", money(sum(by_inst.values()))), ("Usafirishaji (TSh)", money(split["freight"])),
              ("Stoo (TSh)", money(split["storage"])), ("Idadi ya malipo", num(len(detail)))])
    rep.pies([("Kwa benki / njia ya malipo", list(by_inst.items())), ("Kwa mfanyakazi aliyepokea", list(by_staff.items()))])
    days = sorted(by_day, key=lambda s: datetime.strptime(s, "%d/%m/%Y"))
    rep.bars("Malipo kwa siku (TSh)", days, [("Malipo", [by_day[d] for d in days])])
    rep.section("Kwa benki / njia")
    rep.table(["Njia ya malipo", "Kiasi (TSh)"], sorted(([k, v] for k, v in by_inst.items()), key=lambda r: -r[1]),
              widths=[4, 1.5], money={1}, totals={1})
    rep.section("Malipo yote")
    rep.table(["Muda", "Risiti", "Ankara", "Mteja", "Aina", "Njia", "Sarafu", "TSh", "Aliyepokea"], detail,
              widths=[1.3, 1.4, 0.9, 2, 0.8, 1.8, 0.7, 1.2, 1.5], money={7}, totals={7})
    return rep.build()


def expenditure(db, p: Params) -> bytes:
    from ..core.dao import to_uuid

    start, end, label = _period(p)
    from ..expense.dao import approved_filter

    q = db.query(Expense).options(selectinload(Expense.office)).filter(approved_filter())
    if start:
        q = q.filter(Expense.created_at >= start)
    if end:
        q = q.filter(Expense.created_at < end)
    if p.office and to_uuid(p.office):
        q = q.filter(Expense.office_id == to_uuid(p.office))
    expenses = q.order_by(Expense.created_at).all()
    by_office, by_day = {}, {}
    rows = []
    for e in expenses:
        office = e.office[0].name if e.office else "-"
        by_office[office] = by_office.get(office, 0) + (e.amount or 0)
        by_day[_d(e.created_at)] = by_day.get(_d(e.created_at), 0) + (e.amount or 0)
        rows.append([_d(e.created_at), office, e.details, e.amount or 0])
    rep = ReportPdf("Ripoti ya matumizi", label)
    total = sum(r[3] for r in rows)
    rep.kpis([("Matumizi yote (TSh)", money(total)), ("Idadi", num(len(rows))),
              ("Wastani kwa siku (TSh)", money(total / max(len(by_day), 1)))], per_row=3)
    rep.pie("Kwa ofisi", list(by_office.items()))
    rep.table(["Tarehe", "Ofisi", "Maelezo", "Kiasi (TSh)"], rows, widths=[1, 1.5, 4, 1.3], money={3}, totals={3})
    return rep.build()


def _month_key(v) -> str:
    return f"{to_local(v):%Y-%m}"


def summary_data(db: Session, p: Params) -> dict:
    """Muhtasari wa biashara kwa kipindi (JSON kwa app na PDF)."""
    start, end, label = _period(p)
    months: dict = {}

    def m(key):
        return months.setdefault(key, {"invoices": 0, "kg": 0.0, "cartons": 0.0, "billed": 0.0, "collected": 0.0,
                                       "storage": 0.0, "expenses": 0.0})

    by_carrier, by_status, by_inst, by_office = {}, {}, {}, {}
    q = db.query(Invoice).options(selectinload(Invoice.product)).filter(Invoice.status.notin_(_DEAD))
    if start:
        q = q.filter(Invoice.created_at >= start)
    if end:
        q = q.filter(Invoice.created_at < end)
    invoices = _office(q, p).all()
    for inv in invoices:
        row = m(_month_key(inv.created_at))
        row["invoices"] += 1
        by_status[inv.status] = by_status.get(inv.status, 0) + 1
        for x in inv.product:
            row["kg"] += x.weight or 0
            row["cartons"] += x.quantities or 0
            c = (x.carrierType or "AIR").upper()
            agg = by_carrier.setdefault(c, {"kg": 0.0, "cartons": 0.0, "value": 0.0})
            agg["kg"] += x.weight or 0
            agg["cartons"] += x.quantities or 0
            agg["value"] += x.unitPrice or 0
    for d, inv in _debts(db, p, start, end):
        m(_month_key(d.created_at))["billed"] += _billed(d)
    for pay, _debt, inv, inst, _user in _payments(db, p, start, end):
        amount = _signed(pay)
        m(_month_key(pay.created_at))["collected"] += amount
        name = inst.name if inst else "Haijulikani"
        by_inst[name] = by_inst.get(name, 0) + amount
    from ..payment.storage import storage_income

    st = storage_income(db, start, end)
    for item in st["items"]:
        if item.get("paidAt"):
            m(_month_key(datetime.fromisoformat(item["paidAt"])))["storage"] += item["collected"]
    eq = db.query(Expense).options(selectinload(Expense.office))
    if start:
        eq = eq.filter(Expense.created_at >= start)
    if end:
        eq = eq.filter(Expense.created_at < end)
    for e in eq.all():
        m(_month_key(e.created_at))["expenses"] += e.amount or 0
        office = e.office[0].name if e.office else "-"
        by_office[office] = by_office.get(office, 0) + (e.amount or 0)
    keys = sorted(months)
    monthly = [{"month": k, **{kk: round(v, 2) for kk, v in months[k].items()},
                "net": round(months[k]["collected"] - months[k]["expenses"], 2)} for k in keys]
    tot = {k: round(sum(r[k] for r in monthly), 2) for k in
           ("invoices", "kg", "cartons", "billed", "collected", "storage", "expenses", "net")}
    from ..shipment.service import profit_report

    boxes = profit_report(db, p.startDate or (start and f"{to_local(start):%Y-%m-%d}"),
                          p.endDate or (end and f"{to_local(end - timedelta(seconds=1)):%Y-%m-%d}"))
    customers = len({inv.customer_id for inv in invoices})
    return {"label": label, "totals": {**tot, "customers": customers, "boxes": len(boxes.rows),
                                       "boxCosts": boxes.costs, "boxProfit": boxes.profit},
            "monthly": monthly, "byCarrier": {k: {kk: round(v, 2) for kk, v in d.items()} for k, d in by_carrier.items()},
            "byStatus": by_status, "byInstitute": {k: round(v, 2) for k, v in by_inst.items()},
            "expensesByOffice": {k: round(v, 2) for k, v in by_office.items()}}


def summary(db, p: Params) -> bytes:
    s = summary_data(db, p)
    t = s["totals"]
    rep = ReportPdf("Muhtasari wa biashara", s["label"], wide=True)
    rep.kpis([("Ankara mpya", num(t["invoices"])), ("Wateja", num(t["customers"])), ("Kilo", num(t["kg"])),
              ("Katoni", num(t["cartons"])), ("Iliyotozwa (TSh)", money(t["billed"])),
              ("Malipo (TSh)", money(t["collected"])), ("Ya stoo (TSh)", money(t["storage"])),
              ("Matumizi (TSh)", money(t["expenses"])), ("Baki: malipo - matumizi", money(t["net"])),
              ("Mabox yaliyosafirishwa", num(t["boxes"])), ("Gharama za mabox (TSh)", money(t["boxCosts"])),
              ("Faida ya mabox (TSh)", money(t["boxProfit"]))], per_row=4)
    labels = [r["month"] for r in s["monthly"]]
    rep.bars("Kwa mwezi (TSh)", labels, [("Iliyotozwa", [r["billed"] for r in s["monthly"]]),
                                          ("Malipo", [r["collected"] for r in s["monthly"]]),
                                          ("Matumizi", [r["expenses"] for r in s["monthly"]])])
    rep.pies([("Kilo kwa usafiri", [(_carrier_name(k), v["kg"]) for k, v in s["byCarrier"].items()]),
              ("Malipo kwa njia", list(s["byInstitute"].items())),
              ("Matumizi kwa ofisi", list(s["expensesByOffice"].items()))])
    rep.section("Kwa mwezi")
    rep.table(["Mwezi", "Ankara", "Kilo", "Katoni", "Iliyotozwa", "Malipo", "Ya stoo", "Matumizi", "Baki"],
              [[r["month"], r["invoices"], r["kg"], r["cartons"], r["billed"], r["collected"], r["storage"],
                r["expenses"], r["net"]] for r in s["monthly"]],
              widths=[1, 0.8, 1, 0.8, 1.4, 1.4, 1.2, 1.3, 1.3], numbers={1, 2, 3}, money={4, 5, 6, 7, 8},
              totals={1, 2, 3, 4, 5, 6, 7, 8})
    return rep.build()


def customers_data(db: Session, p: Params, limit: int = 100) -> dict:
    start, end, label = _period(p)
    rank: dict = {}
    q = (db.query(Invoice).options(selectinload(Invoice.product), selectinload(Invoice.customer),
                                   selectinload(Invoice.debt)).filter(Invoice.status.notin_(_DEAD)))
    if start:
        q = q.filter(Invoice.created_at >= start)
    if end:
        q = q.filter(Invoice.created_at < end)
    for inv in _office(q, p).all():
        c = inv.customer[0] if inv.customer else None
        if c is None:
            continue
        r = rank.setdefault(c.id, {"customerId": str(c.id), "name": c.name, "phone": c.phoneNumber, "invoices": 0,
                                   "kg": 0.0, "cartons": 0.0, "billed": 0.0, "paid": 0.0, "balance": 0.0})
        d = inv.debt[0] if inv.debt else None
        r["invoices"] += 1
        r["kg"] += sum(x.weight or 0 for x in inv.product)
        r["cartons"] += sum(x.quantities or 0 for x in inv.product)
        r["billed"] += _billed(d) if d else sum(x.unitPrice or 0 for x in inv.product)
        r["paid"] += (d.paid or 0) if d else 0
        r["balance"] += max(d.debt or 0, 0) if d else 0
    rows = sorted(rank.values(), key=lambda r: -r["billed"])
    for r in rows:
        for k in ("kg", "cartons", "billed", "paid", "balance"):
            r[k] = round(r[k], 2)
    return {"label": label, "count": len(rows), "items": rows[:limit],
            "total": round(sum(r["billed"] for r in rows), 2)}


def customers(db, p: Params) -> bytes:
    data = customers_data(db, p, limit=500)
    rows = data["items"]
    rep = ReportPdf("Wateja bora", data["label"], wide=True)
    rep.kpis([("Wateja waliofanya biashara", num(data["count"])), ("Jumla iliyotozwa (TSh)", money(data["total"])),
              ("Wateja 10 wa juu (%)", f"{sum(r['billed'] for r in rows[:10]) / data['total'] * 100:.1f}%"
               if data["total"] else "0%")], per_row=3)
    top = rows[:8]
    rest = sum(r["billed"] for r in rows[8:])
    rep.pie("Mgao wa biashara (TSh)", [(r["name"], r["billed"]) for r in top] + ([("Wengine", rest)] if rest else []))
    rep.table(["#", "Mteja", "Simu", "Ankara", "Katoni", "Kilo", "Iliyotozwa", "Imelipwa", "Deni"],
              [[i, r["name"], r["phone"] or "-", r["invoices"], r["cartons"], r["kg"], r["billed"], r["paid"],
                r["balance"]] for i, r in enumerate(rows, start=1)],
              widths=[0.4, 2.4, 1.6, 0.7, 0.8, 0.9, 1.4, 1.4, 1.3], numbers={0, 3, 4, 5}, money={6, 7, 8},
              totals={3, 4, 5, 6, 7, 8})
    return rep.build()


def boxes(db, p: Params) -> bytes:
    from ..shipment.service import profit_report

    start, end, label = _period(p)
    s_date = p.startDate or f"{to_local(start):%Y-%m-%d}"
    e_date = p.endDate or f"{to_local(end - timedelta(seconds=1)):%Y-%m-%d}"
    rep_data = profit_report(db, s_date, e_date)
    rows = [r for r in rep_data.rows if not p.carrier or (r.packageType or "").upper() == p.carrier.upper()]
    rep = ReportPdf("Mabox yaliyosafirishwa na faida", label, wide=True)
    rev = sum(r.revenue + r.storageCharges for r in rows)
    cost = sum(r.costs for r in rows)
    rep.kpis([("Mabox", num(len(rows))), ("Kilo", num(sum(r.kg for r in rows))), ("Mapato (TSh)", money(rev)),
              ("Gharama (TSh)", money(cost)), ("Faida (TSh)", money(rev - cost)),
              ("Faida %", f"{(rev - cost) / rev * 100:.1f}%" if rev else "0%")], per_row=6)
    by_type = {}
    for r in rows:
        by_type[_carrier_name(r.packageType)] = by_type.get(_carrier_name(r.packageType), 0) + r.kg
    rep.pie("Kilo kwa usafiri", list(by_type.items()), value_fmt=lambda v: f"{num(v)} kg")
    rep.table(["Box", "Aina", "Track", "Lilisafirishwa", "Mizigo", "Kilo", "CBM", "Mapato", "Stoo", "Gharama",
               "Faida", "%"],
              [[r.boxId, _carrier_name(r.packageType), r.trackNumber or "-", _d(r.closedAt), r.items, r.kg, r.cbm,
                r.revenue, r.storageCharges, r.costs, r.profit, f"{r.margin:.1f}%"] for r in rows],
              widths=[1, 0.7, 1.6, 1, 0.7, 0.8, 0.7, 1.2, 1, 1.2, 1.2, 0.6], numbers={4, 5, 6},
              money={7, 8, 9, 10}, totals={4, 5, 6, 7, 8, 9, 10})
    return rep.build()


def storage(db, p: Params) -> bytes:
    from ..payment import storage as st

    start, end, label = _period(p)
    inc = st.storage_income(db, start, end)
    late = st.overdue(db)
    rep = ReportPdf("Mapato ya stoo na mizigo iliyochelewa", label, wide=True)
    rep.kpis([("Malipo yote (TSh)", money(inc["total"])), ("Usafirishaji (TSh)", money(inc["freight"])),
              ("Stoo (TSh)", money(inc["storage"])), ("Stoo isiyolipwa (TSh)", money(inc["pendingInStore"])),
              ("Mizigo iliyochelewa", num(len(late))), ("Gharama yake (TSh)", money(sum(r["storageCharge"] for r in late)))],
             per_row=6)
    rep.pie("Mapato ya kipindi", [("Usafirishaji", inc["freight"]), ("Stoo", inc["storage"])])
    rep.section("Ankara zilizolipia stoo")
    rep.table(["Ankara", "Mteja", "Siku stoo", "Gharama ya stoo", "Imelipwa (stoo)", "Ililipwa"],
              [[r["invoiceNumber"], r["customerName"], r["days"], r["storageCharge"], r["collected"],
                _d(datetime.fromisoformat(r["paidAt"])) if r["paidAt"] else "-"] for r in inc["items"]],
              widths=[1, 2.5, 0.8, 1.3, 1.3, 1], numbers={2}, money={3, 4}, totals={3, 4})
    rep.section("Mizigo iliyochelewa stoo sasa")
    rep.table(["Ankara", "Mteja", "Simu", "Siku", "Siku za kulipia", "USD", "TSh", "Deni lote"],
              [[r["invoiceNumber"], r["customerName"], r["phone"] or "-", r["days"], r["chargeableDays"], r["chargeUsd"],
                r["storageCharge"], r["balance"]] for r in late],
              widths=[1, 2.2, 1.6, 0.6, 1, 0.8, 1.2, 1.2], numbers={3, 4, 5}, money={6, 7}, totals={5, 6, 7})
    db.rollback()  # overdue() husasisha siku bila commit - ripoti haibadilishi data
    return rep.build()


def handovers(db, p: Params) -> bytes:
    from ..handover.search import Filter, search

    start, end, label = _period(p)
    data = search(db, Filter(startDate=p.startDate, endDate=p.endDate, carrier=p.carrier, limit=5000))
    rows = data["items"]
    rep = ReportPdf("Mizigo iliyokabidhiwa", label, wide=True)
    by_staff, by_carrier = {}, {}
    for r in rows:
        by_staff[r["staffName"] or "-"] = by_staff.get(r["staffName"] or "-", 0) + 1
        for i in r["items"]:
            name = _carrier_name(i["carrierType"])
            by_carrier[name] = by_carrier.get(name, 0) + (i["cartons"] or 0)
    rep.kpis([("Makabidhiano", num(len(rows))), ("Katoni", num(sum(r["cartons"] for r in rows))),
              ("Kwa mkopo", num(sum(1 for r in rows if r["onCredit"]))),
              ("Wateja", num(len({r["customerId"] for r in rows})))])
    rep.pies([("Kwa aliyekabidhi", list(by_staff.items())), ("Katoni kwa usafiri", list(by_carrier.items()))])
    rep.table(["Tarehe", "Ankara", "Mteja", "Mizigo", "Usafiri", "Katoni", "Mchukuaji", "Aliyekabidhi", "Mkopo"],
              [[f"{to_local(datetime.fromisoformat(r['created_at'])):%d/%m/%Y %H:%M}" if r["created_at"] else "-",
                r["invoiceNumber"], r["customerName"],
                "; ".join(f"{i['description']} ({num(i['cartons'])})" for i in r["items"])[:90],
                "/".join(_carrier_name(c) for c in r["carriers"]), r["cartons"], r["collectorName"],
                r["staffName"] or "-", "Ndiyo" if r["onCredit"] else "-"] for r in rows],
              widths=[1.3, 0.9, 1.8, 3, 0.8, 0.7, 1.6, 1.5, 0.6], numbers={5}, totals={5})
    return rep.build()


def aging(db, p: Params) -> bytes:
    return debt(db, p.model_copy(update={"status": None}))


def statement(db, p: Params) -> bytes:
    from ..core.dao import to_uuid
    from ..customer.overview import statement_pdf

    if not p.customerId or not to_uuid(p.customerId):
        raise BadRequest("customerId is required")
    content, _ = statement_pdf(db, to_uuid(p.customerId), p.startDate, p.endDate)
    return content


_FN = {"revenue": revenue, "debt": debt, "cargo": cargo, "income": income, "expenditure": expenditure,
       "summary": summary, "customers": customers, "boxes": boxes, "storage": storage, "handovers": handovers,
       "aging": aging, "statement": statement}
_ALIASES = {"range": "revenue", "product": "cargo", "financial-income": "income", "financialIncome": "income"}


def build(db: Session, kind: str, p: Params) -> tuple[bytes, str]:
    kind = _ALIASES.get(kind, kind)
    if kind not in _FN:
        raise BadRequest(f"kind must be one of {', '.join(KINDS)}")
    return _FN[kind](db, p), f"{kind}_{local_now():%Y%m%d_%H%M}"


# --------------------------------------------------- data ya chati za dashibodi
def dashboard_charts(db: Session, office=None) -> dict:
    """Data ya pie charts za dashibodi (mwezi huu)."""
    from ..core.utils import local_midnight_utc
    from .analytics import aging as aging_data

    today = local_now().date()
    month = local_midnight_utc(today.replace(day=1))
    p = Params(office=str(office) if office else None)
    carrier: dict = {}
    q = (db.query(Invoice).options(selectinload(Invoice.product))
         .filter(Invoice.status.notin_(_DEAD), Invoice.created_at >= month))
    for inv in _office(q, p).all():
        for x in inv.product:
            c = (x.carrierType or "AIR").upper()
            carrier[c] = carrier.get(c, 0) + (x.weight or 0)
    methods: dict = {}
    for pay, _d2, _inv, inst, _u in _payments(db, p, month, None):
        name = inst.name if inst else "Haijulikani"
        methods[name] = methods.get(name, 0) + _signed(pay)
    ag = aging_data(db)
    return {"carrierKg": {k: round(v, 2) for k, v in carrier.items()},
            "paymentsByMethod": {k: round(v, 2) for k, v in methods.items() if abs(v) >= 0.5},
            "debtAging": {k: round(v, 2) for k, v in ag["totals"].items()}}
