"""Takwimu za ukurasa wa kwanza wa app (dashboard)."""
from datetime import timedelta

from sqlalchemy.orm import Session

from ..core.utils import local_midnight_utc, local_now, to_local
from . import schema
from .dao import DashboardDao


def summary(db: Session, current_user_id=None) -> schema.Summary:
    from ..core.scope import office_scope

    office = office_scope(db, current_user_id) if current_user_id else None
    dao = DashboardDao(db, office)
    local_today = local_now().date()
    today = local_midnight_utc(local_today)
    month = local_midnight_utc(local_today.replace(day=1))
    week_first = local_today - timedelta(days=6)
    week_start = local_midnight_utc(week_first)

    per_day = {week_first + timedelta(days=i): 0.0 for i in range(7)}
    for created_at, paid in dao.payments_since(week_start):
        day = to_local(created_at).date() if created_at else None
        if day in per_day:
            per_day[day] += paid or 0

    recent = []
    for invoice in dao.recent_invoices(8):
        customer = invoice.customer[0] if invoice.customer else None
        recent.append(schema.RecentInvoice(
            id=invoice.id, invoiceNumber=invoice.invoiceNumber, status=invoice.status,
            customerName=customer.name if customer else None,
            total=sum(p.unitPrice or 0 for p in invoice.product), created_at=invoice.created_at))

    from ..payment import storage

    overdue = len(storage.overdue(db, office=office))
    store_income = storage.storage_income(db, month, None, office)

    from ..report.builder import dashboard_charts

    charts = dashboard_charts(db, office)

    return schema.Summary(
        invoices=dao.invoice_counts(),
        customers=dao.customers(),
        openBoxes=dao.boxes(is_box_close=False, is_collect=False),
        boxesInTransit=dao.boxes(is_box_close=True, is_collect=False),
        lateBoxes=_late_boxes(db),
        outstandingDebt=dao.outstanding_debt(),
        paidToday=dao.paid_since(today),
        paidThisMonth=dao.paid_since(month),
        expensesThisMonth=dao.expenses_since(month),
        pendingSms=dao.pending_sms(),
        income7Days=[schema.DayAmount(date=d.isoformat(), amount=v) for d, v in sorted(per_day.items())],
        recentInvoices=recent,
        storageIncomeThisMonth=store_income["storage"],
        storagePending=store_income["pendingInStore"],
        overdueInStore=overdue,
        **charts,
    )




def hide_money(s: schema.Summary) -> schema.Summary:
    """Kwa asiye na ruhusa ya kuona pesa: idadi zinabaki, kiasi cha pesa kinakuwa 0."""
    return s.model_copy(update={
        "outstandingDebt": 0.0, "paidToday": 0.0, "paidThisMonth": 0.0, "expensesThisMonth": 0.0,
        "storageIncomeThisMonth": 0.0, "storagePending": 0.0, "paymentsByMethod": {}, "debtAging": {},
        "income7Days": [schema.DayAmount(date=d.date, amount=0.0) for d in s.income7Days],
        "recentInvoices": [r.model_copy(update={"total": 0.0}) for r in s.recentInvoices],
        "finance": False,
    })


def _late_boxes(db) -> int:
    from ..core.base_model import utc_now
    from ..package.model import Package

    return (db.query(Package).filter(Package.isBoxClose.is_(True), Package.isCollect.is_(False),
                                     Package.eta.isnot(None), Package.eta < utc_now().date()).count())
