"""
Dashibodi ya mteja mmoja: takwimu zote na kumbukumbu zote za biashara naye
(ankara na mizigo, malipo, makabidhiano, madai, SMS) - kwa app, PDF (taarifa ya mteja) na Excel.
"""
from datetime import datetime

from sqlalchemy.orm import Session, selectinload

from ..core.enums import EInvoiceStatus, EPaymentKind
from ..core.exceptions import NotFound
from ..core.utils import day_range, product_cbm, to_local
from ..invoice.model import Invoice
from ..payment.model import Debt, Payment
from ..settings.institute.model import Institute
from ..user.model import User
from .model import Customer

_DEAD = {EInvoiceStatus.BLOCKED.name, EInvoiceStatus.BLOCK.name}


def _iso(v: datetime | None) -> str | None:
    return v.isoformat(timespec="seconds") if v else None


def _month(v: datetime | None) -> str | None:
    return f"{to_local(v):%Y-%m}" if v else None


def _credit(db: Session, customer) -> dict:
    from ..payment import credit

    return credit.status(db, customer)


def overview(db: Session, customer_id, start_date: str | None = None, end_date: str | None = None) -> dict:
    customer = db.get(Customer, customer_id) if customer_id else None
    if customer is None:
        raise NotFound("The Customer does not exist")
    start, end = day_range(start_date, end_date)

    q = (db.query(Invoice).filter(Invoice.customer_id == customer.id)
         .options(selectinload(Invoice.product), selectinload(Invoice.debt), selectinload(Invoice.receiver),
                  selectinload(Invoice.handover)))
    if start is not None:
        q = q.filter(Invoice.created_at >= start)
    if end is not None:
        q = q.filter(Invoice.created_at < end)
    invoices = q.order_by(Invoice.created_at.desc()).all()
    invoice_ids = [i.id for i in invoices]
    debt_by_invoice = {i.id: (i.debt[0] if i.debt else None) for i in invoices}
    number = {i.id: i.invoiceNumber for i in invoices}

    users = {u.id: f"{u.firstName} {u.lastName}" for u in db.query(User).all()}

    # ------------------------------------------------------------ ankara + mizigo
    inv_rows, by_carrier, by_status, monthly = [], {}, {}, {}
    totals = dict(invoices=0, active=0, cartons=0.0, kg=0.0, cbm=0.0, value=0.0, billed=0.0, paid=0.0, balance=0.0,
                  storage=0.0, discount=0.0, products=0)
    for inv in invoices:
        d = debt_by_invoice[inv.id]
        products = inv.product or []
        cartons = sum(p.quantities or 0 for p in products)
        kg = sum(p.weight or 0 for p in products)
        cbm = sum(product_cbm(p) for p in products)
        value = sum(p.unitPrice or 0 for p in products)
        billed = ((d.amount or 0) + (d.storageCharge or 0) - (d.discount or 0)) if d else 0.0
        paid = (d.paid or 0) if d else 0.0
        balance = max((d.debt or 0), 0) if d else 0.0
        carriers = sorted({(p.carrierType or "").upper() for p in products if p.carrierType})
        by_status[inv.status] = by_status.get(inv.status, 0) + 1
        if inv.status not in _DEAD:
            totals["invoices"] += 1
            if inv.status not in (EInvoiceStatus.COMPLETED.name,):
                totals["active"] += 1
            totals["cartons"] += cartons
            totals["kg"] += kg
            totals["cbm"] += cbm
            totals["value"] += value
            totals["billed"] += billed
            totals["paid"] += paid
            totals["balance"] += balance
            totals["storage"] += (d.storageCharge or 0) if d else 0
            totals["discount"] += (d.discount or 0) if d else 0
            totals["products"] += len(products)
            for p in products:
                c = (p.carrierType or "AIR").upper()
                agg = by_carrier.setdefault(c, {"kg": 0.0, "cartons": 0.0, "value": 0.0, "items": 0})
                agg["kg"] += p.weight or 0
                agg["cartons"] += p.quantities or 0
                agg["value"] += p.unitPrice or 0
                agg["items"] += 1
            m = monthly.setdefault(_month(inv.created_at), {"invoices": 0, "kg": 0.0, "billed": 0.0, "paid": 0.0})
            m["invoices"] += 1
            m["kg"] += kg
            m["billed"] += billed or value
        receiver = inv.receiver[0] if inv.receiver else None
        inv_rows.append({
            "id": str(inv.id), "invoiceNumber": inv.invoiceNumber, "status": inv.status,
            "created_at": _iso(inv.created_at), "cartons": cartons, "kg": round(kg, 2), "cbm": round(cbm, 3),
            "carriers": carriers, "value": round(value, 2), "billed": round(billed, 2), "paid": round(paid, 2),
            "balance": round(balance, 2), "storageCharge": round((d.storageCharge or 0) if d else 0, 2),
            "storageDays": (d.days or 0) if d else 0, "discount": round((d.discount or 0) if d else 0, 2),
            "receiverName": receiver.name if receiver else None, "pickupCode": receiver.trackNumber if receiver else None,
            "handovers": len(inv.handover or []),
            "products": [{"description": p.description, "cartons": p.quantities or 0, "kg": p.weight or 0,
                          "trackNumber": p.trackNumber, "carrierType": p.carrierType, "price": p.unitPrice or 0}
                         for p in products],
        })

    # ------------------------------------------------------------ malipo
    pay_rows, by_method = [], {}
    if invoice_ids:
        rows = (db.query(Payment, Debt, Institute).join(Debt, Debt.id == Payment.debt_id)
                .outerjoin(Institute, Institute.id == Payment.institute_id)
                .filter(Debt.invoice_id.in_(invoice_ids)).order_by(Payment.created_at.desc()).all())
        refunds = 0.0
        for pay, debt, inst in rows:
            refund = pay.kind == EPaymentKind.REFUND.name
            amount = (pay.paid or 0) * (-1 if refund else 1)
            if refund:
                refunds += pay.paid or 0
            name = inst.name if inst else "Haijulikani"
            by_method[name] = by_method.get(name, 0) + amount
            m = monthly.setdefault(_month(pay.created_at), {"invoices": 0, "kg": 0.0, "billed": 0.0, "paid": 0.0})
            m["paid"] += amount
            pay_rows.append({"id": str(pay.id), "created_at": _iso(pay.created_at), "receiptNumber": pay.receiptNumber,
                             "invoiceId": str(debt.invoice_id), "invoiceNumber": number.get(debt.invoice_id),
                             "kind": pay.kind, "amount": round(amount, 2), "currency": pay.currency or "TZS",
                             "amountOriginal": pay.amountOriginal, "institute": name, "note": pay.note,
                             "staff": users.get(pay.logsId)})
        totals["refunds"] = round(refunds, 2)
    else:
        totals["refunds"] = 0.0

    # ------------------------------------------------------------ makabidhiano, madai, sms
    handovers = []
    for inv in invoices:
        for h in inv.handover or []:
            handovers.append({"id": str(h.id), "invoiceId": str(inv.id), "invoiceNumber": inv.invoiceNumber,
                              "created_at": _iso(h.created_at), "collectorName": h.collectorName,
                              "collectorPhone": h.collectorPhone, "onCredit": bool(h.onCredit),
                              "staff": users.get(h.logsId)})
    handovers.sort(key=lambda r: r["created_at"] or "", reverse=True)

    claims = []
    if invoice_ids:
        from ..claim.model import CargoClaim

        for cl in (db.query(CargoClaim).filter(CargoClaim.invoice_id.in_(invoice_ids))
                   .order_by(CargoClaim.created_at.desc()).all()):
            claims.append({"id": str(cl.id), "invoiceId": str(cl.invoice_id), "invoiceNumber": number.get(cl.invoice_id),
                           "type": cl.type, "status": cl.status, "description": cl.description,
                           "compensation": cl.compensation or 0, "created_at": _iso(cl.created_at)})

    sms = []
    if invoice_ids or customer.phoneNumber:
        from sqlalchemy import or_

        from ..sms.model import Sms

        conds = []
        if invoice_ids:
            conds.append(Sms.invoice_id.in_(invoice_ids))
        if customer.phoneNumber:
            conds.append(Sms.msisdn == customer.phoneNumber)
        for s in db.query(Sms).filter(or_(*conds)).order_by(Sms.created_at.desc()).limit(300).all():
            sms.append({"id": str(s.id), "created_at": _iso(s.created_at), "kind": s.smsFor, "channel": s.channel,
                        "text": s.text, "sent": bool(s.isSMSSend), "invoiceNumber": number.get(s.invoice_id)})

    dates = [i.created_at for i in invoices if i.created_at]
    months = sorted(k for k in monthly if k)[-12:]
    return {
        "customer": {"id": str(customer.id), "name": customer.name, "phoneNumber": customer.phoneNumber,
                     "active": customer.active, "created_at": _iso(customer.created_at),
                     "creditLimit": customer.creditLimit},
        "credit": _credit(db, customer),
        "finance": True,
        "period": {"startDate": start_date, "endDate": end_date},
        "stats": {**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in totals.items()},
                  "firstAt": _iso(min(dates)) if dates else None, "lastAt": _iso(max(dates)) if dates else None,
                  "payments": len(pay_rows), "handovers": len(handovers), "claims": len(claims), "sms": len(sms)},
        "byCarrier": {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in by_carrier.items()},
        "byStatus": by_status,
        "byMethod": {k: round(v, 2) for k, v in by_method.items()},
        "monthly": [{"month": k, **{kk: round(vv, 2) for kk, vv in monthly[k].items()}} for k in months],
        "invoices": inv_rows, "payments": pay_rows, "handovers": handovers, "claims": claims, "sms": sms,
    }


def hide_money(o: dict) -> dict:
    """Kwa asiye na ruhusa ya FINANCE: mizigo na kumbukumbu zinabaki, pesa zinaondolewa."""
    money = ("billed", "paid", "balance", "storage", "discount", "refunds", "value")
    o = dict(o)
    o["stats"] = {k: (0 if k in money else v) for k, v in o["stats"].items()}
    o["stats"]["payments"] = 0
    o["invoices"] = [{**i, "value": 0, "billed": 0, "paid": 0, "balance": 0, "storageCharge": 0, "discount": 0,
                      "products": [{**p, "price": 0} for p in i["products"]]} for i in o["invoices"]]
    o["payments"] = []
    o["byMethod"] = {}
    o["monthly"] = [{**m, "billed": 0, "paid": 0} for m in o["monthly"]]
    o["credit"] = {"limit": None, "used": 0, "available": None, "unlimited": True, "hidden": True}
    o["finance"] = False
    return o


# ------------------------------------------------------------------- PDF / Excel
_STATUS = {"OPEN": "Inapokea", "PARKING": "Tayari kupakiwa", "SHIPPING": "Safarini", "STORE": "Stoo",
           "DELIVERED": "Imekabidhiwa (deni)", "COMPLETED": "Imekamilika", "BLOCKED": "Imezuiwa", "BLOCK": "Imezuiwa"}


def _d(v: str | None) -> str:
    return f"{to_local(datetime.fromisoformat(v)):%d/%m/%Y}" if v else "-"


def statement_pdf(db: Session, customer_id, start_date=None, end_date=None) -> tuple[bytes, str]:
    from ..core.report_pdf import ReportPdf, money, num

    o = overview(db, customer_id, start_date, end_date)
    c, s = o["customer"], o["stats"]
    period = f"{start_date or 'mwanzo'} hadi {end_date or 'leo'}"
    rep = ReportPdf("Taarifa ya mteja", period, wide=True, subtitle=c["name"])
    rep.kpis([("Mteja", c["name"]), ("Simu", c["phoneNumber"] or "-"), ("Mteja tangu", _d(c["created_at"])),
              ("Ankara", num(s["invoices"])),
              ("Jumla iliyotozwa (TSh)", money(s["billed"])), ("Imelipwa (TSh)", money(s["paid"])),
              ("Deni lililobaki (TSh)", money(s["balance"])), ("Gharama za stoo (TSh)", money(s["storage"])),
              ("Katoni", num(s["cartons"])), ("Kilo", num(s["kg"])), ("Punguzo (TSh)", money(s["discount"])),
              ("Refund (TSh)", money(s["refunds"]))], per_row=4)
    rep.pies([
        ("Mizigo kwa usafiri (kg)", [("Ndege" if k == "AIR" else "Meli" if k == "SEA" else k, v["kg"])
                                     for k, v in o["byCarrier"].items()]),
        ("Malipo kwa njia", list(o["byMethod"].items())),
    ])
    rep.bars("Biashara kwa mwezi (TSh)", [m["month"] for m in o["monthly"]],
             [("Iliyotozwa", [m["billed"] for m in o["monthly"]]), ("Imelipwa", [m["paid"] for m in o["monthly"]])])
    rep.section("Ankara na mizigo")
    rep.table(["Tarehe", "Ankara", "Hali", "Mizigo", "Usafiri", "Katoni", "Kg", "Iliyotozwa", "Imelipwa", "Deni"],
              [[_d(i["created_at"]), i["invoiceNumber"], _STATUS.get(i["status"], i["status"]),
                ", ".join(p["description"] for p in i["products"])[:80],
                "/".join("Ndege" if x == "AIR" else "Meli" for x in i["carriers"]), i["cartons"], i["kg"],
                i["billed"], i["paid"], i["balance"]] for i in o["invoices"]],
              widths=[1.1, 1, 1.3, 3.2, 0.9, 0.7, 0.8, 1.2, 1.2, 1.1], numbers={5, 6}, money={7, 8, 9},
              totals={5, 6, 7, 8, 9})
    rep.section("Malipo")
    rep.table(["Tarehe", "Risiti", "Ankara", "Aina", "Njia", "Sarafu", "Kiasi (TSh)", "Aliyepokea"],
              [[_d(p["created_at"]), p["receiptNumber"] or "-", p["invoiceNumber"] or "-",
                "Refund" if p["kind"] == "REFUND" else "Malipo", p["institute"], p["currency"], p["amount"],
                p["staff"] or "-"] for p in o["payments"]],
              widths=[1.1, 1.3, 1, 0.8, 1.6, 0.7, 1.3, 1.6], money={6}, totals={6})
    rep.section("Makabidhiano")
    rep.table(["Tarehe", "Ankara", "Mchukuaji", "Simu", "Mkopo", "Aliyekabidhi"],
              [[_d(h["created_at"]), h["invoiceNumber"], h["collectorName"], h["collectorPhone"] or "-",
                "Ndiyo" if h["onCredit"] else "Hapana", h["staff"] or "-"] for h in o["handovers"]],
              widths=[1, 1, 2, 1.5, 0.8, 1.8])
    if o["claims"]:
        rep.section("Madai")
        rep.table(["Tarehe", "Ankara", "Aina", "Hali", "Maelezo", "Fidia (TSh)"],
                  [[_d(x["created_at"]), x["invoiceNumber"], x["type"], x["status"], x["description"],
                    x["compensation"]] for x in o["claims"]],
                  widths=[1, 1, 1, 1, 4, 1.2], money={5}, totals={5})
    safe = "".join(ch for ch in c["name"] if ch.isalnum() or ch in " _-").strip().replace(" ", "_") or "mteja"
    return rep.build(), f"taarifa_{safe}"


def statement_excel(db: Session, customer_id, start_date=None, end_date=None) -> tuple[bytes, str]:
    from ..core import excel

    o = overview(db, customer_id, start_date, end_date)
    c = o["customer"]
    label = f"{c['name']} ({c['phoneNumber'] or '-'})"
    dt = lambda v: to_local(datetime.fromisoformat(v)) if v else None  # noqa: E731
    sheets = [
        excel.Sheet("Ankara", ["Tarehe", "Ankara", "Hali", "Mizigo", "Usafiri", "Katoni", "Kg", "CBM", "Thamani",
                               "Stoo", "Punguzo", "Iliyotozwa", "Imelipwa", "Deni"],
                    [[dt(i["created_at"]), i["invoiceNumber"], _STATUS.get(i["status"], i["status"]),
                      "; ".join(p["description"] for p in i["products"]), "/".join(i["carriers"]), i["cartons"],
                      i["kg"], i["cbm"], i["value"], i["storageCharge"], i["discount"], i["billed"], i["paid"],
                      i["balance"]] for i in o["invoices"]],
                    money={8, 9, 10, 11, 12, 13}, totals={5, 6, 7, 8, 9, 10, 11, 12, 13}, subtitle=label),
        excel.Sheet("Mizigo", ["Ankara", "Mzigo", "Track", "Usafiri", "Katoni", "Kg", "Bei"],
                    [[i["invoiceNumber"], p["description"], p["trackNumber"] or "", p["carrierType"], p["cartons"],
                      p["kg"], p["price"]] for i in o["invoices"] for p in i["products"]],
                    money={6}, totals={4, 5, 6}, subtitle=label),
        excel.Sheet("Malipo", ["Tarehe", "Risiti", "Ankara", "Aina", "Njia", "Sarafu", "Kiasi (sarafu)", "TSh",
                               "Aliyepokea", "Maelezo"],
                    [[dt(p["created_at"]), p["receiptNumber"] or "", p["invoiceNumber"] or "", p["kind"],
                      p["institute"], p["currency"], p["amountOriginal"] or "", p["amount"], p["staff"] or "",
                      p["note"] or ""] for p in o["payments"]],
                    money={7}, totals={7}, subtitle=label),
        excel.Sheet("Makabidhiano", ["Tarehe", "Ankara", "Mchukuaji", "Simu", "Mkopo", "Aliyekabidhi"],
                    [[dt(h["created_at"]), h["invoiceNumber"], h["collectorName"], h["collectorPhone"] or "",
                      "Ndiyo" if h["onCredit"] else "Hapana", h["staff"] or ""] for h in o["handovers"]],
                    subtitle=label),
        excel.Sheet("SMS", ["Tarehe", "Aina", "Njia", "Ankara", "Imetumwa", "Ujumbe"],
                    [[dt(x["created_at"]), x["kind"], x["channel"], x["invoiceNumber"] or "",
                      "Ndiyo" if x["sent"] else "Hapana", x["text"]] for x in o["sms"]], subtitle=label),
    ]
    safe = "".join(ch for ch in c["name"] if ch.isalnum() or ch in " _-").strip().replace(" ", "_") or "mteja"
    return excel.build(sheets), f"mteja_{safe}"
