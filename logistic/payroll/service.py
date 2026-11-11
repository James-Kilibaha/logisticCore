"""
Mishahara ya kila mwezi.

    gross       = mshahara wa msingi + posho
    NSSF (mf.)  = gross x nssfEmployee%            (kama mfanyakazi anachangia)
    taxable     = gross - NSSF ya mfanyakazi
    PAYE        = kwa bendi (zinazobadilishwa kwenye Mipangilio ya mishahara)
    net         = gross - NSSF - PAYE - makato mengine
    mwajiri     = NSSF (mwajiri) + SDL + WCF

Mshahara ukiidhinishwa (POST) unaingia kwenye Uhasibu:
- "Mishahara <mwezi>" (kwa kila ofisi): gross; kilicholipwa = net (+ makato mengine) kutoka akaunti iliyochaguliwa;
  PAYE + NSSF ya mfanyakazi = DENI kwa TRA / NSSF (linaonekana kwenye Madeni na linalipwa baadaye).
- "Michango ya mwajiri <mwezi>": NSSF (mwajiri) + SDL + WCF = deni lote.
"""
import json

from sqlalchemy.orm import Session

from ..core.audit import note
from ..core.base_model import utc_now
from ..core.dao import to_uuid
from ..core.exceptions import BadRequest, Conflict, NotFound
from ..core.utils import local_now, whole
from .model import Employee, PayrollLine, PayrollRun, PayrollSettings

# Tanzania bara (kwa mwezi, TSh) - THIBITISHA na TRA; zinabadilishwa kwenye Mipangilio ya mishahara.
DEFAULT_BANDS = [[0, 270000, 0, 0], [270000, 520000, 0, 8], [520000, 760000, 20000, 20],
                 [760000, 1000000, 68000, 25], [1000000, None, 128000, 30]]


# ------------------------------------------------------------------ viwango
def settings(db: Session) -> PayrollSettings:
    row = db.query(PayrollSettings).first()
    if row is None:
        row = PayrollSettings(nssfEmployee=10.0, nssfEmployer=10.0, sdl=3.5, sdlEnabled=False, wcf=0.5,
                              payeBands=json.dumps(DEFAULT_BANDS))
        db.add(row)
        db.commit()
    return row


def bands(row: PayrollSettings) -> list:
    try:
        data = json.loads(row.payeBands or "")
        return data if isinstance(data, list) and data else DEFAULT_BANDS
    except ValueError:
        return DEFAULT_BANDS


def settings_dict(db: Session) -> dict:
    row = settings(db)
    return {"nssfEmployee": row.nssfEmployee, "nssfEmployer": row.nssfEmployer, "sdl": row.sdl,
            "sdlEnabled": row.sdlEnabled, "wcf": row.wcf, "payeBands": bands(row)}


def save_settings(db: Session, data) -> dict:
    for v in (data.nssfEmployee, data.nssfEmployer, data.sdl, data.wcf):
        if not 0 <= v <= 50:
            raise BadRequest("Asilimia si sahihi")
    clean = []
    for b in data.payeBands:
        if len(b) != 4:
            raise BadRequest("Kila bendi ya PAYE iwe [kuanzia, mpaka, kiasi, asilimia]")
        lo, hi, fixed, pct = b
        if lo is None or lo < 0 or (hi is not None and hi <= lo) or not 0 <= (pct or 0) <= 100:
            raise BadRequest("Bendi ya PAYE si sahihi")
        clean.append([float(lo), None if hi is None else float(hi), float(fixed or 0), float(pct or 0)])
    row = settings(db)
    row.nssfEmployee, row.nssfEmployer, row.sdl, row.wcf = data.nssfEmployee, data.nssfEmployer, data.sdl, data.wcf
    row.sdlEnabled = data.sdlEnabled
    row.payeBands = json.dumps(sorted(clean, key=lambda b: b[0]) or DEFAULT_BANDS)
    db.commit()
    note("Viwango vya mishahara (PAYE/NSSF/SDL/WCF) vimebadilishwa")
    return settings_dict(db)


def paye(taxable: float, band_list: list) -> float:
    for lo, hi, fixed, pct in band_list:
        if taxable > lo and (hi is None or taxable <= hi):
            return round((fixed or 0) + (taxable - lo) * (pct or 0) / 100, 2)
    return 0.0


# ------------------------------------------------------------------ wafanyakazi
def _emp_row(e: Employee, offices: dict) -> dict:
    return {"id": str(e.id), "name": e.name, "phone": e.phone, "position": e.position,
            "office_id": str(e.office_id) if e.office_id else None, "office": offices.get(e.office_id),
            "basic": e.basic, "allowance": e.allowance, "deduction": e.deduction, "nssf": e.nssf, "paye": e.paye,
            "tin": e.tin, "nssfNo": e.nssfNo, "bank": e.bank, "active": e.active}


def _offices(db: Session) -> dict:
    from ..settings.office.model import Office

    return {o.id: o.name for o in db.query(Office).all()}


def employees(db: Session, include_inactive: bool = False) -> list[dict]:
    q = db.query(Employee).filter(Employee.isBlocked.is_(False))
    if not include_inactive:
        q = q.filter(Employee.active.is_(True))
    offices = _offices(db)
    return [_emp_row(e, offices) for e in q.order_by(Employee.name).all()]


def save_employee(db: Session, data, user_id, employee_id=None) -> dict:
    fields = {"name": data.name.strip(), "phone": (data.phone or "").strip() or None,
              "position": (data.position or "").strip() or None, "office_id": data.office_id,
              "basic": round(data.basic, 2), "allowance": round(data.allowance or 0, 2),
              "deduction": round(data.deduction or 0, 2), "nssf": data.nssf, "paye": data.paye,
              "tin": (data.tin or "").strip() or None, "nssfNo": (data.nssfNo or "").strip() or None,
              "bank": (data.bank or "").strip() or None, "active": data.active}
    if employee_id is None:
        e = Employee(**fields, logsId=user_id)
        db.add(e)
    else:
        e = db.get(Employee, to_uuid(employee_id))
        if e is None or e.isBlocked:
            raise NotFound("Mfanyakazi hayupo")
        for k, v in fields.items():
            setattr(e, k, v)
    db.commit()
    note(f"Mfanyakazi: {e.name} (mshahara TSh {whole(e.basic)})")
    return _emp_row(e, _offices(db))


def delete_employee(db: Session, employee_id) -> dict:
    e = db.get(Employee, to_uuid(employee_id))
    if e is None:
        raise NotFound("Mfanyakazi hayupo")
    if db.query(PayrollLine.id).filter(PayrollLine.employee_id == e.id).first():
        e.isBlocked, e.active = True, False   # historia ya mishahara inabaki
        db.commit()
        return {"deleted": True, "archived": True}
    db.delete(e)
    db.commit()
    return {"deleted": True, "archived": False}


# ------------------------------------------------------------------ mishahara ya mwezi
def _compute(line: PayrollLine, cfg: PayrollSettings, nssf: bool, taxed: bool) -> None:
    line.gross = round((line.basic or 0) + (line.allowance or 0), 2)
    line.nssfEmployee = round(line.gross * cfg.nssfEmployee / 100, 2) if nssf else 0.0
    line.taxable = round(line.gross - line.nssfEmployee, 2)
    line.paye = paye(line.taxable, bands(cfg)) if taxed else 0.0
    line.net = round(line.gross - line.nssfEmployee - line.paye - (line.deduction or 0), 2)
    line.nssfEmployer = round(line.gross * cfg.nssfEmployer / 100, 2) if nssf else 0.0
    line.sdl = round(line.gross * cfg.sdl / 100, 2) if cfg.sdlEnabled else 0.0
    line.wcf = round(line.gross * cfg.wcf / 100, 2)


def _line_row(line: PayrollLine, offices: dict) -> dict:
    return {k: getattr(line, k) for k in ("name", "position", "basic", "allowance", "gross", "nssfEmployee", "taxable",
                                          "paye", "deduction", "net", "nssfEmployer", "sdl", "wcf")} | {
        "id": str(line.id), "employee_id": str(line.employee_id) if line.employee_id else None,
        "office": offices.get(line.office_id)}


_TOTALS = ("gross", "nssfEmployee", "paye", "deduction", "net", "nssfEmployer", "sdl", "wcf")


def _run_row(db: Session, run: PayrollRun) -> dict:
    lines = db.query(PayrollLine).filter(PayrollLine.run_id == run.id).order_by(PayrollLine.name).all()
    offices = _offices(db)
    totals = {k: round(sum(getattr(x, k) or 0 for x in lines), 2) for k in _TOTALS}
    totals["employerCost"] = round(totals["gross"] + totals["nssfEmployer"] + totals["sdl"] + totals["wcf"], 2)
    return {"id": str(run.id), "month": run.month, "status": run.status, "note": run.note,
            "institute_id": str(run.institute_id) if run.institute_id else None,
            "lines": [_line_row(x, offices) for x in lines], "totals": totals,
            "created_at": run.created_at.isoformat() if run.created_at else None}


def runs(db: Session) -> list[dict]:
    out = []
    for run in db.query(PayrollRun).order_by(PayrollRun.month.desc()).all():
        row = _run_row(db, run)
        row.pop("lines")
        out.append(row)
    return out


def _run(db: Session, run_id) -> PayrollRun:
    run = db.get(PayrollRun, to_uuid(run_id))
    if run is None:
        raise NotFound("Mishahara ya mwezi huu haipo")
    return run


def get_run(db: Session, run_id) -> dict:
    return _run_row(db, _run(db, run_id))


def prepare(db: Session, month: str, user_id) -> dict:
    """Andaa (au andaa upya) mishahara ya mwezi kutoka kwa wafanyakazi hai - DRAFT."""
    import re

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise BadRequest("Mwezi si sahihi (YYYY-MM)")
    from ..accounting.locks import is_locked
    from ..core.utils import local_midnight_utc, parse_date

    if is_locked(db, local_midnight_utc(parse_date(f"{month}-01"))):
        raise BadRequest(f"Mwezi {month} umefungwa")
    run = db.query(PayrollRun).filter(PayrollRun.month == month).first()
    if run is not None and run.status == "POSTED":
        raise Conflict("Mishahara ya mwezi huu imeshaidhinishwa")
    staff = db.query(Employee).filter(Employee.active.is_(True), Employee.isBlocked.is_(False)).all()
    if not staff:
        raise BadRequest("Hakuna wafanyakazi - waongeze kwanza")
    if run is None:
        run = PayrollRun(month=month, status="DRAFT", logsId=user_id)
        db.add(run)
        db.flush()
    else:
        db.query(PayrollLine).filter(PayrollLine.run_id == run.id).delete(synchronize_session=False)
    cfg = settings(db)
    for e in staff:
        line = PayrollLine(run_id=run.id, employee_id=e.id, name=e.name, position=e.position, office_id=e.office_id,
                           basic=e.basic or 0, allowance=e.allowance or 0, deduction=e.deduction or 0)
        _compute(line, cfg, e.nssf, e.paye)
        db.add(line)
    db.commit()
    return _run_row(db, run)


def edit_line(db: Session, run_id, line_id, data) -> dict:
    """Badilisha posho / makato ya mwezi huu tu (mf. overtime, mkopo)."""
    run = _run(db, run_id)
    if run.status != "DRAFT":
        raise BadRequest("Mishahara iliyoidhinishwa haibadilishwi")
    line = db.get(PayrollLine, to_uuid(line_id))
    if line is None or line.run_id != run.id:
        raise NotFound("Mstari haupo")
    emp = db.get(Employee, line.employee_id) if line.employee_id else None
    line.basic = round(data.basic, 2) if data.basic is not None else line.basic
    line.allowance, line.deduction = round(data.allowance or 0, 2), round(data.deduction or 0, 2)
    _compute(line, settings(db), emp.nssf if emp else True, emp.paye if emp else True)
    db.commit()
    return _run_row(db, run)


def post(db: Session, run_id, institute_id, user_id) -> dict:
    """Idhinisha: mishahara inaingia Uhasibu (matumizi + madeni ya PAYE/NSSF/SDL/WCF)."""
    from ..accounting.locks import ensure_open
    from ..accounting.model import AccountCategory
    from ..accounting.service import _account
    from ..expense.model import Expense, ExpensePayment

    ensure_open(db)
    run = _run(db, run_id)
    if run.status != "DRAFT":
        raise BadRequest("Mishahara hii imeshaidhinishwa")
    if institute_id is not None:
        _account(db, institute_id)
    lines = db.query(PayrollLine).filter(PayrollLine.run_id == run.id).all()
    if not lines:
        raise BadRequest("Hakuna mistari ya mishahara")
    cat = (db.query(AccountCategory).filter(AccountCategory.kind == "EXPENSE", AccountCategory.isBlocked.is_(False),
                                            AccountCategory.name.ilike("mishahara%")).first())
    if cat is None:
        cat = AccountCategory(name="Mishahara", kind="EXPENSE", logsId=user_id)
        db.add(cat)
        db.flush()
    by_office: dict = {}
    for x in lines:
        by_office.setdefault(x.office_id, []).append(x)
    now = utc_now()
    first_salary = first_employer = None
    for office_id, group in by_office.items():
        gross = round(sum(x.gross for x in group), 2)
        statutory = round(sum(x.paye + x.nssfEmployee for x in group), 2)
        paid = round(gross - statutory, 2)   # net + makato mengine
        employer = round(sum(x.nssfEmployer + x.sdl + x.wcf for x in group), 2)
        salary = Expense(details=f"Mishahara {run.month} (watu {len(group)})", amount=gross, office_id=office_id,
                         currency="TZS", category_id=cat.id, institute_id=institute_id, status="APPROVED",
                         approvedBy=to_uuid(user_id), approvedAt=now,
                         payStatus="PAID" if statutory <= 0 else ("PARTIAL" if paid > 0 else "CREDIT"),
                         paidTzs=paid, supplier="TRA (PAYE) / NSSF" if statutory > 0 else None, logsId=user_id)
        db.add(salary)
        db.flush()
        if paid > 0:
            db.add(ExpensePayment(expense_id=salary.id, amount=paid, currency="TZS", institute_id=institute_id,
                                  initial=True, note=f"Mishahara {run.month} (net)", logsId=user_id))
        first_salary = first_salary or salary.id
        if employer > 0:
            contrib = Expense(details=f"Michango ya mwajiri {run.month} (NSSF/SDL/WCF)", amount=employer,
                              office_id=office_id, currency="TZS", category_id=cat.id, status="APPROVED",
                              approvedBy=to_uuid(user_id), approvedAt=now, payStatus="CREDIT", paidTzs=0.0,
                              supplier="NSSF / TRA (SDL) / WCF", logsId=user_id)
            db.add(contrib)
            db.flush()
            first_employer = first_employer or contrib.id
    run.status, run.institute_id, run.postedBy = "POSTED", institute_id, to_uuid(user_id)
    run.salaryExpense_id, run.employerExpense_id = first_salary, first_employer
    db.commit()
    note(f"Mishahara ya {run.month} imeidhinishwa (TSh {whole(sum(x.gross for x in lines))})")
    return _run_row(db, run)


def delete_run(db: Session, run_id) -> bool:
    """DRAFT: inafutwa. POSTED: inafutwa pamoja na matumizi yake kama madeni yake hayajaanza kulipwa."""
    from ..accounting.locks import ensure_open
    from ..expense.model import Expense, ExpensePayment

    run = _run(db, run_id)
    if run.status == "POSTED":
        ensure_open(db, run.created_at)
        mine = db.query(Expense).filter(Expense.details.like(f"Mishahara {run.month} (%")
                                        | Expense.details.like(f"Michango ya mwajiri {run.month} (%")).all()
        if mine and db.query(ExpensePayment.id).filter(ExpensePayment.expense_id.in_([e.id for e in mine]),
                                                       ExpensePayment.initial.is_(False)).first():
            raise BadRequest("Madeni ya mishahara hii yameshaanza kulipwa - haiwezi kufutwa")
        for e in mine:
            db.delete(e)
    db.delete(run)
    db.commit()
    note(f"Mishahara ya {run.month} imefutwa")
    return True


# ------------------------------------------------------------------ ripoti
def sheet_excel(db: Session, run_id) -> tuple[bytes, str]:
    from ..core import excel

    d = get_run(db, run_id)
    headers = ["Jina", "Cheo", "Ofisi", "Msingi", "Posho", "Gross", "NSSF (mf.)", "Taxable", "PAYE", "Makato",
               "Net", "NSSF (mwajiri)", "SDL", "WCF"]
    rows = [[x["name"], x["position"] or "", x["office"] or "", x["basic"], x["allowance"], x["gross"],
             x["nssfEmployee"], x["taxable"], x["paye"], x["deduction"], x["net"], x["nssfEmployer"], x["sdl"], x["wcf"]]
            for x in d["lines"]]
    cols = set(range(3, 14))
    sheet = excel.Sheet(f"Mishahara {d['month']}", headers, rows, money=cols, totals=cols,
                        subtitle=f"Hali: {d['status']}")
    return excel.build([sheet]), f"mishahara_{d['month']}"


def sheet_pdf(db: Session, run_id) -> tuple[bytes, str]:
    from ..core.report_pdf import ReportPdf, money

    d = get_run(db, run_id)
    t = d["totals"]
    rep = ReportPdf("Mishahara", d["month"], wide=True, subtitle=f"Hali: {d['status']}")
    rep.kpis([("Gross", money(t["gross"])), ("PAYE", money(t["paye"])), ("NSSF (mf.)", money(t["nssfEmployee"])),
              ("Net", money(t["net"])), ("Gharama ya mwajiri", money(t["employerCost"]))])
    rep.table(["Jina", "Gross", "NSSF", "PAYE", "Makato", "Net", "NSSF mw.", "SDL", "WCF"],
              [[x["name"], x["gross"], x["nssfEmployee"], x["paye"], x["deduction"], x["net"], x["nssfEmployer"],
                x["sdl"], x["wcf"]] for x in d["lines"]],
              widths=[4, 2, 2, 2, 2, 2, 2, 2, 2], money=set(range(1, 9)), totals=set(range(1, 9)))
    rep.note("Viwango vya PAYE/NSSF/SDL/WCF vinatoka Mipangilio ya mishahara - vithibitishe na TRA/NSSF.")
    return rep.build(), f"mishahara_{d['month']}"


def current_month() -> str:
    return local_now().strftime("%Y-%m")
