"""Ripoti za data (JSON + Excel): umri wa madeni na faili za Excel za kupakua."""
from datetime import datetime

from sqlalchemy.orm import Session, selectinload

from ..core import excel
from ..core.enums import EInvoiceStatus, EPaymentStatus
from ..core.exceptions import BadRequest
from ..core.utils import day_range, local_now, to_local
from ..customer.model import Customer
from ..expense.model import Expense
from ..invoice.model import Invoice
from ..payment.model import Debt, Payment
from ..settings.institute.model import Institute
from ..user.model import User

BUCKETS = ("0-7", "8-30", "31-60", "60+")


def _bucket(days: int) -> str:
    if days <= 7:
        return "0-7"
    if days <= 30:
        return "8-30"
    if days <= 60:
        return "31-60"
    return "60+"


def _naive_iso(value: str | None):
    """ISO ya UTC (kutoka storage.py) -> saa za hapa, kwa Excel."""
    return to_local(datetime.fromisoformat(value)) if value else None


def _naive(dt: datetime | None):
    return to_local(dt) if dt else None


def aging(db: Session) -> dict:
    """Madeni yote ambayo hayajalipwa, kwa umri tangu ankara ilipotolewa (deni lilipofunguliwa)."""
    today = local_now().date()
    rows = (db.query(Debt, Invoice).join(Invoice, Invoice.id == Debt.invoice_id)
            .options(selectinload(Invoice.customer))
            .filter(Debt.status != EPaymentStatus.PAID.name, Debt.debt >= 1,
                    Invoice.status.notin_([EInvoiceStatus.BLOCKED.name, EInvoiceStatus.BLOCK.name]))
            .all())
    invoices, customers = [], {}
    totals = {b: 0.0 for b in BUCKETS}
    for debt, invoice in rows:
        opened = to_local(debt.created_at).date() if debt.created_at else today
        days = (today - opened).days
        bucket = _bucket(days)
        customer = invoice.customer[0] if invoice.customer else None
        balance = round(debt.debt or 0, 2)
        totals[bucket] += balance
        invoices.append({
            "invoiceId": str(invoice.id), "invoiceNumber": invoice.invoiceNumber, "status": invoice.status,
            "customerId": str(customer.id) if customer else None, "customerName": customer.name if customer else "-",
            "phone": (customer.phoneNumber if customer else None) or "", "days": days, "bucket": bucket,
            "total": round((debt.amount or 0) + (debt.storageCharge or 0) - (debt.discount or 0), 2),
            "paid": round(debt.paid or 0, 2), "balance": balance,
        })
        key = str(customer.id) if customer else "-"
        c = customers.setdefault(key, {"customerId": key, "customerName": customer.name if customer else "-",
                                       "phone": (customer.phoneNumber if customer else None) or "", "invoices": 0,
                                       "oldestDays": 0, "total": 0.0, **{b: 0.0 for b in BUCKETS}})
        c["invoices"] += 1
        c["oldestDays"] = max(c["oldestDays"], days)
        c["total"] += balance
        c[bucket] += balance
    invoices.sort(key=lambda r: -r["days"])
    by_customer = sorted(customers.values(), key=lambda r: -r["total"])
    return {"buckets": list(BUCKETS), "totals": {k: round(v, 2) for k, v in totals.items()},
            "total": round(sum(totals.values()), 2), "customers": by_customer, "invoices": invoices}


# ------------------------------------------------------------------ Excel
EXPORTS = ("invoices", "payments", "expenses", "aging", "profit", "customers", "storage")


def _period(start_date, end_date) -> tuple:
    start, end = day_range(start_date, end_date)
    label = f"Kipindi: {start_date or 'mwanzo'} hadi {end_date or 'leo'}"
    return start, end, label


def export(db: Session, kind: str, start_date: str | None, end_date: str | None) -> tuple[bytes, str]:
    if kind not in EXPORTS:
        raise BadRequest(f"kind must be one of {', '.join(EXPORTS)}")
    start, end, label = _period(start_date, end_date)
    stamp = f"{local_now():%Y%m%d}"

    if kind == "invoices":
        q = db.query(Invoice).options(selectinload(Invoice.customer), selectinload(Invoice.product),
                                      selectinload(Invoice.debt))
        if start:
            q = q.filter(Invoice.created_at >= start)
        if end:
            q = q.filter(Invoice.created_at < end)
        rows = []
        for inv in q.order_by(Invoice.invoiceNumber).all():
            c = inv.customer[0] if inv.customer else None
            d = inv.debt[0] if inv.debt else None
            rows.append([inv.invoiceNumber, _naive(inv.created_at), c.name if c else "", (c.phoneNumber if c else None) or "",
                         inv.status, sum(p.quantities or 0 for p in inv.product), round(sum(p.weight or 0 for p in inv.product), 2),
                         sum(p.unitPrice or 0 for p in inv.product), d.storageCharge if d else 0,
                         d.discount if d else 0, d.paid if d else 0, max(d.debt or 0, 0) if d else 0])
        sheet = excel.Sheet("Ankara", ["Ankara", "Tarehe", "Mteja", "Simu", "Hali", "Katoni", "Kilo",
                                       "Usafirishaji", "Stoo", "Punguzo", "Imelipwa", "Baki"], rows,
                            money={7, 8, 9, 10, 11}, totals={5, 6, 7, 8, 9, 10, 11}, subtitle=label)
    elif kind == "payments":
        q = (db.query(Payment, Debt, Invoice, Institute, User)
             .join(Debt, Debt.id == Payment.debt_id).join(Invoice, Invoice.id == Debt.invoice_id)
             .outerjoin(Institute, Institute.id == Payment.institute_id).outerjoin(User, User.id == Payment.logsId)
             .options(selectinload(Invoice.customer)))
        if start:
            q = q.filter(Payment.created_at >= start)
        if end:
            q = q.filter(Payment.created_at < end)
        rows = []
        for pay, _debt, inv, inst, user in q.order_by(Payment.created_at).all():
            c = inv.customer[0] if inv.customer else None
            sign = -1 if pay.kind == "REFUND" else 1
            rows.append([_naive(pay.created_at), pay.receiptNumber or "", inv.invoiceNumber, c.name if c else "",
                         "Refund" if sign < 0 else "Malipo", inst.name if inst else "", pay.currency or "TZS",
                         pay.amountOriginal or "", sign * (pay.paid or 0), user.username if user else "", pay.note or ""])
        sheet = excel.Sheet("Malipo", ["Muda", "Risiti", "Ankara", "Mteja", "Aina", "Kupitia", "Sarafu",
                                       "Kiasi (sarafu)", "TSh", "Aliyepokea", "Maelezo"], rows,
                            money={8}, totals={8}, subtitle=label)
    elif kind == "expenses":
        from ..expense.dao import approved_filter

        q = db.query(Expense).options(selectinload(Expense.office)).filter(approved_filter())
        if start:
            q = q.filter(Expense.created_at >= start)
        if end:
            q = q.filter(Expense.created_at < end)
        rows = [[_naive(e.created_at), e.details, e.office[0].name if e.office else "", e.amount or 0]
                for e in q.order_by(Expense.created_at).all()]
        sheet = excel.Sheet("Matumizi", ["Tarehe", "Maelezo", "Ofisi", "Kiasi"], rows, money={3}, totals={3},
                            subtitle=label)
    elif kind == "aging":
        data = aging(db)
        rows = [[r["invoiceNumber"], r["customerName"], r["phone"], r["status"], r["days"], r["bucket"],
                 r["total"], r["paid"], r["balance"]] for r in data["invoices"]]
        sheet = excel.Sheet("Madeni kwa umri", ["Ankara", "Mteja", "Simu", "Hali", "Siku", "Kundi", "Jumla",
                                                "Imelipwa", "Baki"], rows, money={6, 7, 8}, totals={6, 7, 8},
                            subtitle=f"Hadi {local_now():%d/%m/%Y}")
        by_c = [[r["customerName"], r["phone"], r["invoices"], r["oldestDays"], *[r[b] for b in BUCKETS], r["total"]]
                for r in data["customers"]]
        sheet2 = excel.Sheet("Kwa mteja", ["Mteja", "Simu", "Ankara", "Siku (ya zamani zaidi)",
                                           *[f"Siku {b}" for b in BUCKETS], "Jumla"], by_c,
                             money={4, 5, 6, 7, 8}, totals={4, 5, 6, 7, 8})
        return excel.build([sheet, sheet2]), f"madeni_umri_{stamp}"
    elif kind == "profit":
        from ..shipment.service import profit_report

        rep = profit_report(db, start_date, end_date)
        rows = [[r.boxId, "Meli" if r.packageType == "SEA" else "Ndege", r.trackNumber or "", _naive(r.closedAt),
                 r.items, r.kg, r.cbm, r.revenue, r.storageCharges, r.costs, r.profit, r.margin] for r in rep.rows]
        sheet = excel.Sheet("Faida kwa box", ["Box", "Aina", "Track", "Lilisafirishwa", "Mizigo", "Kilo", "CBM",
                                              "Mapato", "Stoo", "Gharama", "Faida", "Faida %"], rows,
                            money={7, 8, 9, 10}, totals={4, 5, 7, 8, 9, 10}, subtitle=label)
    elif kind == "storage":
        from ..payment import storage

        income = storage.storage_income(db, start, end)
        rows = [[r["invoiceNumber"], r["customerName"], r["status"], r["days"], _naive_iso(r["paidAt"]),
                 r["storageCharge"], r["collected"]] for r in income["items"]]
        sheet = excel.Sheet("Mapato ya stoo", ["Ankara", "Mteja", "Hali", "Siku stoo", "Ililipwa",
                                               "Gharama ya stoo", "Imelipwa (stoo)"], rows,
                            money={5, 6}, totals={5, 6},
                            subtitle=f"{label}  |  Jumla ya mapato TSh {income['total']:,.0f}: usafirishaji "
                                     f"{income['freight']:,.0f}, stoo {income['storage']:,.0f}")
        late = storage.overdue(db)
        rows2 = [[r["invoiceNumber"], r["customerName"], r["phone"], r["days"], r["chargeableDays"], r["chargeUsd"],
                  r["storageCharge"], r["balance"], _naive_iso(r["remindedAt"])] for r in late]
        sheet2 = excel.Sheet("Mizigo iliyochelewa stoo", ["Ankara", "Mteja", "Simu", "Siku stoo",
                                                         "Siku za kulipia", "USD", "Gharama (TSh)", "Deni lote",
                                                         "Kumbusho la mwisho"], rows2,
                             money={6, 7}, totals={5, 6, 7}, subtitle=f"Hadi {local_now():%d/%m/%Y}")
        db.commit()
        return excel.build([sheet, sheet2]), f"mapato_stoo_{stamp}"
    else:  # customers
        customers = db.query(Customer).options(selectinload(Customer.invoice)).order_by(Customer.name).all()
        owing: dict = {}
        for cid, amount in db.query(Invoice.customer_id, Debt.debt).join(Debt, Debt.invoice_id == Invoice.id) \
                .filter(Debt.status != EPaymentStatus.PAID.name).all():
            owing[cid] = owing.get(cid, 0) + max(amount or 0, 0)
        rows = [[c.name, c.phoneNumber or "", "Hai" if c.active == 1 else "Amezuiwa", _naive(c.created_at),
                 len(c.invoice or []), owing.get(c.id, 0)] for c in customers]
        sheet = excel.Sheet("Wateja", ["Jina", "Simu", "Hali", "Alisajiliwa", "Ankara", "Deni"], rows,
                            money={5}, totals={4, 5})
    return excel.build([sheet]), f"{kind}_{stamp}"
