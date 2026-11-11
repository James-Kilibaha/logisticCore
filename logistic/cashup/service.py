"""
Kufunga hesabu ya siku (cash-up): mhasibu analinganisha malipo yaliyorekodiwa na mfumo kwa kila njia
(benki / simu / taslimu) na pesa halisi aliyoihesabu. Tofauti ikiwepo, wasimamizi wanapata taarifa.
"""
from datetime import date, timedelta
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from ..core.base_model import utc_now
from ..core.enums import EPaymentKind
from ..core.exceptions import BadRequest, Conflict, NotFound
from ..core.utils import local_midnight_utc, local_now, parse_date, to_local, whole
from ..invoice.model import Invoice
from ..payment.model import Debt, Payment
from ..settings.institute.model import Institute
from ..user.model import User
from .model import CashUp, CashUpLine

NO_METHOD = "Bila njia"


class Line(BaseModel):
    instituteId: UUID | None = None
    counted: float = Field(0, ge=0)
    note: str | None = None


class Close(BaseModel):
    day: str | None = None          # YYYY-MM-DD (tupu = leo)
    office: UUID | None = None
    lines: list[Line] = Field(default_factory=list)
    note: str | None = None


def _day(value: str | None) -> date:
    d = parse_date(value) if value else local_now().date()
    if d is None:
        raise BadRequest("day must be YYYY-MM-DD")
    if d > local_now().date():
        raise BadRequest("Huwezi kufunga hesabu ya siku ijayo / cannot close a future day")
    return d


def _payments(db: Session, d: date, office=None, since=None):
    start, end = local_midnight_utc(d), local_midnight_utc(d + timedelta(days=1))
    q = (db.query(Payment).join(Debt, Debt.id == Payment.debt_id).join(Invoice, Invoice.id == Debt.invoice_id)
         .filter(Payment.created_at >= start, Payment.created_at < end))
    if office is not None:
        q = q.filter(or_(Invoice.office_id == office, Invoice.office_id.is_(None)))
    if since is not None:
        q = q.filter(Payment.created_at > since)
    return q.all()


def _existing(db: Session, d: date, office=None) -> CashUp | None:
    q = db.query(CashUp).options(selectinload(CashUp.lines)).filter(CashUp.day == d.isoformat())
    q = q.filter(CashUp.office_id == office) if office is not None else q.filter(CashUp.office_id.is_(None))
    return q.first()


def _by_method(db: Session, payments) -> dict:
    names = {i.id: i.name for i in db.query(Institute).all()}
    out: dict = {}
    for p in payments:
        key = p.institute_id
        row = out.setdefault(key, {"instituteId": str(key) if key else None,
                                   "name": names.get(key, NO_METHOD) if key else NO_METHOD,
                                   "expected": 0.0, "payments": 0, "refunds": 0.0})
        amount = (p.paid or 0) * (-1 if p.kind == EPaymentKind.REFUND.name else 1)
        row["expected"] += amount
        row["payments"] += 1
        if amount < 0:
            row["refunds"] += -amount
    return out


def _display(db: Session, c: CashUp) -> dict:
    user = db.get(User, c.logsId) if c.logsId else None
    late = _payments(db, parse_date(c.day), c.office_id, since=c.closedAt)
    return {"id": str(c.id), "day": c.day, "office": str(c.office_id) if c.office_id else None,
            "expected": round(c.expected, 2), "counted": round(c.counted, 2), "difference": round(c.difference, 2),
            "payments": c.payments, "note": c.note, "closedAt": c.closedAt.isoformat() if c.closedAt else None,
            "closedBy": f"{user.firstName} {user.lastName}" if user else None,
            "lateCount": len(late),
            "lateAmount": round(sum((p.paid or 0) * (-1 if p.kind == EPaymentKind.REFUND.name else 1) for p in late), 2),
            "lines": [{"instituteId": str(x.institute_id) if x.institute_id else None, "name": x.name,
                       "expected": round(x.expected, 2), "counted": round(x.counted, 2),
                       "difference": round(x.difference, 2), "payments": x.payments, "note": x.note}
                      for x in sorted(c.lines, key=lambda r: r.name)]}


def expected(db: Session, day: str | None, office=None) -> dict:
    """Malipo ya siku kwa kila njia (kabla ya kufunga), na rekodi ya kufunga kama ipo."""
    d = _day(day)
    pays = _payments(db, d, office)
    methods = sorted(_by_method(db, pays).values(), key=lambda r: r["name"])
    # njia zote za malipo zionekane (hata zisizo na malipo leo) ili kiasi halisi kiandikwe
    shown = {m["instituteId"] for m in methods}
    for inst in db.query(Institute).order_by(Institute.name).all():
        if str(inst.id) not in shown:
            methods.append({"instituteId": str(inst.id), "name": inst.name, "expected": 0.0, "payments": 0,
                            "refunds": 0.0})
    for m in methods:
        m["expected"] = round(m["expected"], 2)
    closed = _existing(db, d, office)
    return {"day": d.isoformat(), "office": str(office) if office else None, "methods": methods,
            "total": round(sum(m["expected"] for m in methods), 2), "payments": len(pays),
            "closed": _display(db, closed) if closed else None}


def close(db: Session, data: Close, user_id) -> dict:
    from ..core.audit import note
    from ..notification.service import notify

    d = _day(data.day)
    if _existing(db, d, data.office):
        raise Conflict("Hesabu ya siku hii imeshafungwa / this day is already closed")
    pays = _payments(db, d, data.office)
    methods = _by_method(db, pays)
    counted_by = {}
    for line in data.lines:
        key = line.instituteId
        if key in counted_by:
            raise BadRequest("Njia ya malipo imerudiwa / duplicate payment method")
        counted_by[key] = line
    names = {i.id: i.name for i in db.query(Institute).all()}
    keys = set(methods) | set(counted_by)
    now = utc_now()
    cash = CashUp(day=d.isoformat(), office_id=data.office, note=(data.note or "").strip() or None, closedAt=now,
                  logsId=user_id, payments=len(pays))
    total_e = total_c = 0.0
    for key in keys:
        exp = round(methods.get(key, {}).get("expected", 0.0), 2)
        line = counted_by.get(key)
        cnt = round(line.counted if line else 0.0, 2)
        name = names.get(key, NO_METHOD) if key else NO_METHOD
        if key is not None and key not in names:
            raise BadRequest("Njia ya malipo haipo / unknown payment method")
        cash.lines.append(CashUpLine(institute_id=key, name=name, expected=exp, counted=cnt,
                                     difference=round(cnt - exp, 2), payments=methods.get(key, {}).get("payments", 0),
                                     note=(line.note or "").strip() or None if line else None, logsId=user_id))
        total_e += exp
        total_c += cnt
    cash.expected, cash.counted, cash.difference = round(total_e, 2), round(total_c, 2), round(total_c - total_e, 2)
    db.add(cash)
    db.flush()
    if abs(cash.difference) >= 1:
        sign = "zaidi" if cash.difference > 0 else "pungufu"
        notify(db, "PAYMENT", "update", kind="CASHUP_DIFF", link="cashup",
               title=f"Tofauti ya hesabu {d:%d/%m/%Y}: TSh {whole(abs(cash.difference))} ({sign})",
               body=f"Mfumo TSh {whole(cash.expected)}, iliyohesabiwa TSh {whole(cash.counted)}", exclude=user_id)
    db.commit()
    note(f"Hesabu ya {d:%d/%m/%Y} imefungwa: mfumo {whole(cash.expected)}, halisi {whole(cash.counted)}, "
         f"tofauti {whole(cash.difference)}")
    db.refresh(cash)
    return _display(db, cash)


def history(db: Session, start_date: str | None, end_date: str | None, office=None) -> dict:
    q = db.query(CashUp).options(selectinload(CashUp.lines))
    if start_date:
        q = q.filter(CashUp.day >= start_date)
    if end_date:
        q = q.filter(CashUp.day <= end_date)
    if office is not None:
        q = q.filter(CashUp.office_id == office)
    rows = [_display(db, c) for c in q.order_by(CashUp.day.desc()).limit(400).all()]
    return {"items": rows, "expected": round(sum(r["expected"] for r in rows), 2),
            "counted": round(sum(r["counted"] for r in rows), 2),
            "difference": round(sum(r["difference"] for r in rows), 2),
            "short": round(sum(r["difference"] for r in rows if r["difference"] < 0), 2),
            "over": round(sum(r["difference"] for r in rows if r["difference"] > 0), 2)}


def reopen(db: Session, cashup_id) -> bool:
    from ..core.audit import note

    c = db.get(CashUp, cashup_id)
    if c is None:
        raise NotFound("Cash-up not found")
    day = c.day
    db.delete(c)
    db.commit()
    note(f"Hesabu ya {day} imefunguliwa upya")
    return True


def pdf(db: Session, cashup_id) -> tuple[bytes, str]:
    from ..core.report_pdf import ReportPdf, money, num

    c = db.query(CashUp).options(selectinload(CashUp.lines)).filter(CashUp.id == cashup_id).first()
    if c is None:
        raise NotFound("Cash-up not found")
    d = _display(db, c)
    rep = ReportPdf("Kufunga hesabu ya siku", f"{parse_date(c.day):%d/%m/%Y}",
                    subtitle=f"Imefungwa na {d['closedBy'] or '-'}")
    rep.kpis([("Mfumo (TSh)", money(d["expected"])), ("Iliyohesabiwa (TSh)", money(d["counted"])),
              ("Tofauti (TSh)", money(d["difference"])), ("Malipo", num(d["payments"]))])
    rep.table(["Njia ya malipo", "Malipo", "Mfumo", "Iliyohesabiwa", "Tofauti", "Maelezo"],
              [[x["name"], x["payments"], x["expected"], x["counted"], x["difference"], x["note"] or ""]
               for x in d["lines"]],
              widths=[2.2, 0.8, 1.3, 1.3, 1.2, 2.5], numbers={1}, money={2, 3, 4}, totals={1, 2, 3, 4})
    if d["note"]:
        rep.note(f"Maelezo: {d['note']}")
    if d["lateCount"]:
        rep.note(f"Tahadhari: malipo {d['lateCount']} (TSh {whole(d['lateAmount'])}) yaliingizwa baada ya kufunga hesabu.")
    rep.note(f"Imefungwa: {to_local(c.closedAt):%d/%m/%Y %H:%M}" if c.closedAt else "")
    return rep.build(), f"hesabu_{c.day}"
