"""Ripoti zote zinatoka kama PDF kutoka template za Word (assets/sample/*.docx)."""
from datetime import datetime

from sqlalchemy.orm import Session

from ..core import documents, files
from ..core.exceptions import BadRequest
from ..core.utils import day_range, money, parse_date, whole
from . import schema
from .dao import ReportDao


def _range(f: schema.Range) -> tuple[datetime, datetime, str]:
    start, end = day_range(f.startDate, f.endDate)
    if start is None or end is None:
        raise BadRequest("startDate and endDate are required")
    if start >= end:
        raise BadRequest("startDate must be before endDate")
    return start, end, f"{start:%d/%m/%Y} - {parse_date(f.endDate):%d/%m/%Y}"


def _debt(invoice):
    return invoice.debt[0] if invoice.debt else None


def _names(invoice) -> str:
    return ",".join(p.description for p in invoice.product) or "-"


def _sum(invoice, field: str) -> float:
    return sum(getattr(p, field) or 0 for p in invoice.product)


def range_report(db: Session, f: schema.Range):
    if not f.status:
        raise BadRequest("status is required")
    start, end, label = _range(f)
    rows, total = [], 0.0
    for sn, invoice in enumerate(ReportDao(db).invoices_by_debt_status_between(f.status, start, end), start=1):
        paid = _debt(invoice).paid if _debt(invoice) else 0.0
        total += paid
        rows.append([f"{sn}", _names(invoice), _sum(invoice, "weight"), _sum(invoice, "quantities"), money(paid)])
    path = f"{files.REPORT_DIR}/{f.status}_{start:%d%m%Y}_{parse_date(f.endDate):%d%m%Y}"
    return documents.render_pdf("range", {"totalRevenue": money(total), "monthYear": label,
                                          "list": rows, "total": money(total)}, path)


def debt_report(db: Session, f: schema.Range):
    rows, total, total_debt = [], 0.0, 0.0
    for sn, invoice in enumerate(ReportDao(db).invoices_with_debt(f.status), start=1):
        debt = _debt(invoice)
        total += debt.paid
        total_debt += debt.debt
        rows.append([f"{sn}", _names(invoice), _sum(invoice, "quantities"), money(debt.debt), money(debt.paid)])
    path = f"{files.REPORT_DIR}/{f.status or 'debt'}"
    return documents.render_pdf("debt", {"totalRevenue": money(total), "monthYear": f"{datetime.today():%d/%m/%Y}",
                                         "list": rows, "totalDebt": money(total_debt), "total": money(total)}, path)


def product_report(db: Session, f: schema.Range):
    start, end, label = _range(f)
    rows, total, total_quantity = [], 0.0, 0.0
    for sn, invoice in enumerate(ReportDao(db).invoices_between(start, end), start=1):
        amount = _debt(invoice).amount if _debt(invoice) else 0.0
        quantity = _sum(invoice, "quantities")
        total += amount
        total_quantity += quantity
        customer = invoice.customer[0].name if invoice.customer else "-"
        rows.append([f"{sn}", _names(invoice), customer, whole(quantity), money(amount)])
    return documents.render_pdf("product", {"totalRevenue": money(total), "monthYear": label, "list": rows,
                                            "totalQuant": whole(total_quantity), "total": money(total)},
                                f"{files.REPORT_DIR}/product")


def financial_income_report(db: Session, f: schema.Range):
    start, end, label = _range(f)
    rows, total = [], 0.0
    for sn, row in enumerate(ReportDao(db).income_by_institute(start, end), start=1):
        total += row.total or 0
        rows.append([f"{sn}", f"{row.name} [{row.currencyType}]", money(row.total)])
    return documents.render_pdf("financialIncome", {"totalRevenue": money(total), "monthYear": label,
                                                    "list": rows, "total": money(total)},
                                f"{files.REPORT_DIR}/financialIncome")


def expenditure_report(db: Session, f: schema.Range):
    start, end, label = _range(f)
    rows, total = [], 0.0
    for sn, expense in enumerate(ReportDao(db).expenses_between(start, end, f.office), start=1):
        total += expense.amount or 0
        office = expense.office[0].name if expense.office else "-"
        rows.append([sn, office, expense.details, money(expense.amount)])
    return documents.render_pdf("expenditure", {"totalRevenue": money(total), "monthYear": label,
                                                "list": rows, "total": money(total)},
                                f"{files.REPORT_DIR}/expenditure")
