from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..core.security import get_current_user
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Report"], prefix="/api/report",
                   dependencies=[Depends(require(Module.REPORT, Action.SELECT))])


def _pdf(path):
    return FileResponse(path, media_type="application/pdf")


def _report(db: Session, kind: str, request) -> Response:
    """PDF ya ripoti (reportlab) - tazama report/builder.py."""
    from . import builder

    params = builder.Params(**(request.model_dump() if hasattr(request, "model_dump") else dict(request)))
    content, name = builder.build(db, kind, params)
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


# Ripoti zenye pesa (mapato, madeni, matumizi, wateja kwa kiasi) zinahitaji FINANCE; faida inahitaji PROFIT.
# Ripoti za kazi (mizigo, makabidhiano, stoo) zinahitaji REPORT tu.
MONEY_KINDS = {"range", "debt", "income", "expenditure", "summary", "customers", "aging", "statement",
               "invoices", "payments", "expenses"}
PROFIT_KINDS = {"boxes", "profit"}


def _profit_guard(db: Session, kind: str, user_id) -> None:
    from ..core.permission import need

    if kind in PROFIT_KINDS:
        need(db, user_id, Module.PROFIT)
    elif kind in MONEY_KINDS:
        need(db, user_id, Module.FINANCE)


_money = require(Module.FINANCE, Action.SELECT)


@router.post("/pdf/{kind}", status_code=status.HTTP_200_OK)
def report_pdf(kind: str, request: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Ripoti yoyote ya PDF: revenue, debt, cargo, income, expenditure, summary, customers, boxes, storage,
    handovers, aging, statement (customerId)."""
    from . import builder

    _profit_guard(db, kind, current_user.id)
    content, name = builder.build(db, kind, builder.Params(**{k: v for k, v in (request or {}).items()
                                                               if k in builder.Params.model_fields}))
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@router.get("/summary", status_code=status.HTTP_200_OK)
def business_summary(startDate: str | None = None, endDate: str | None = None, office: str | None = None,
                     db: Session = Depends(get_db), _f=Depends(_money)):
    """Muhtasari wa biashara kwa kipindi: kwa mwezi, usafiri, njia za malipo, matumizi kwa ofisi."""
    from . import builder

    return builder.summary_data(db, builder.Params(startDate=startDate, endDate=endDate, office=office))


@router.get("/top-customers", status_code=status.HTTP_200_OK)
def top_customers(startDate: str | None = None, endDate: str | None = None, limit: int = 50,
                  db: Session = Depends(get_db), _f=Depends(_money)):
    """Wateja bora kwa kipindi (kwa kiasi kilichotozwa)."""
    from . import builder

    return builder.customers_data(db, builder.Params(startDate=startDate, endDate=endDate), limit=max(1, min(limit, 500)))


@router.post("/range", status_code=status.HTTP_200_OK)
def range_report(request: schema.Range, db: Session = Depends(get_db), _f=Depends(_money)):
    return _report(db, "range", request)


@router.post("/debt", status_code=status.HTTP_200_OK)
def debt_report(request: schema.Range, db: Session = Depends(get_db), _f=Depends(_money)):
    return _report(db, "debt", request)


@router.post("/product", status_code=status.HTTP_200_OK)
def product_report(request: schema.Range, db: Session = Depends(get_db)):
    return _report(db, "product", request)


@router.post("/financial-income", status_code=status.HTTP_200_OK)
def financial_income_report(request: schema.Range, db: Session = Depends(get_db), _f=Depends(_money)):
    return _report(db, "income", request)


@router.post("/expenditure", status_code=status.HTTP_200_OK)
def expenditure_report(request: schema.Range, db: Session = Depends(get_db), _f=Depends(_money)):
    return _report(db, "expenditure", request)


@router.get("/aging", status_code=status.HTTP_200_OK)
def aging_report(db: Session = Depends(get_db), _f=Depends(_money)):
    """Madeni ambayo hayajalipwa kwa umri wake (siku 0-7, 8-30, 31-60, 60+), kwa mteja na kwa ankara."""
    from . import analytics

    return analytics.aging(db)


@router.get("/income", status_code=status.HTTP_200_OK)
def income_breakdown(startDate: str | None = None, endDate: str | None = None, db: Session = Depends(get_db), _f=Depends(_money)):
    """Mapato ya kipindi: jumla, ya usafirishaji na ya stoo (gharama za kuhifadhi mizigo)."""
    from ..core.utils import day_range
    from ..payment import storage

    start, end = day_range(startDate, endDate)
    return storage.storage_income(db, start, end)


@router.get("/export/{kind}", status_code=status.HTTP_200_OK)
def export_excel(kind: str, startDate: str | None = None, endDate: str | None = None, db: Session = Depends(get_db),
                 current_user=Depends(get_current_user)):
    """Excel: invoices, payments, expenses, aging, profit, customers, storage."""
    from . import analytics

    _profit_guard(db, kind, current_user.id)
    content, name = analytics.export(db, kind, startDate, endDate)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
