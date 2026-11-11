from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Customer"], prefix="/api/customer")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_customer(request: schema.Insert, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.CUSTOMER, Action.INSERT))):
    return service.create(db, request, current_user.id)


@router.put("/update", status_code=status.HTTP_201_CREATED)
def update_customer(request: schema.Update, db: Session = Depends(get_db),
                    _=Depends(require(Module.CUSTOMER, Action.UPDATE))):
    return service.update(db, request)


@router.get("", status_code=status.HTTP_200_OK)
def get_all_customers(db: Session = Depends(get_db), _=Depends(require(Module.CUSTOMER, Action.SELECT))):
    return service.list_all(db)


@router.post("/search", status_code=status.HTTP_200_OK)
def search_customers(request: schema.Search, db: Session = Depends(get_db),
                     _=Depends(require(Module.CUSTOMER, Action.SELECT))):
    """Kurasa: `limit`/`offset`; `q` = jina au namba ya simu."""
    return service.search(db, request)


@router.get("/counts", status_code=status.HTTP_200_OK)
def customer_counts(db: Session = Depends(get_db), _=Depends(require(Module.CUSTOMER, Action.SELECT))):
    return service.counts(db)


@router.get("/not-block", status_code=status.HTTP_200_OK)
def get_not_blocked_customers(db: Session = Depends(get_db), _=Depends(require(Module.CUSTOMER, Action.SELECT))):
    return service.list_not_blocked(db)


@router.put("/credit-limit", status_code=status.HTTP_200_OK)
def set_credit_limit(request: schema.CreditLimit, db: Session = Depends(get_db),
                     _=Depends(require(Module.CREDIT, Action.UPDATE))):
    """Kikomo cha mkopo cha mteja (TSh). null = tumia kikomo cha kawaida (DEFAULT_CREDIT_LIMIT); 0 = hakuna mkopo."""
    return service.set_credit_limit(db, request)


@router.get("/{id}/credit", status_code=status.HTTP_200_OK)
def credit_status(id: str, db: Session = Depends(get_db), _=Depends(require(Module.CREDIT, Action.SELECT))):
    """Kikomo, kinachotumika na kinachopatikana."""
    return service.credit_status(db, id)


@router.get("/{status}", status_code=status.HTTP_200_OK)
def get_customers_by_invoice_status(status: str, db: Session = Depends(get_db),
                                    _=Depends(require(Module.CUSTOMER, Action.SELECT))):
    return service.by_invoice_status(db, status)


@router.put("/block", status_code=status.HTTP_200_OK)
def block_customer(request: schema.Block, db: Session = Depends(get_db),
                   _=Depends(require(Module.CUSTOMER, Action.BLOCK))):
    return service.toggle_block(db, request)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
def delete_customer(id: str, db: Session = Depends(get_db), _=Depends(require(Module.CUSTOMER, Action.DELETE))):
    return service.delete(db, id)


# ------------------------------------------------------------ dashibodi ya mteja
@router.get("/{id}/overview", status_code=status.HTTP_200_OK)
def customer_overview(id: str, startDate: str | None = None, endDate: str | None = None,
                      db: Session = Depends(get_db), current_user=Depends(require(Module.CUSTOMER, Action.SELECT))):
    """Takwimu na kumbukumbu zote za biashara na mteja: ankara, mizigo, malipo, makabidhiano, madai, SMS."""
    from ..core.dao import to_uuid
    from ..permission.dao import PermissionDao
    from .overview import hide_money, overview

    data = overview(db, to_uuid(id), startDate, endDate)
    if not PermissionDao(db).has(current_user.id, Module.FINANCE.value, Action.SELECT.value):
        data = hide_money(data)
    return data


@router.get("/{id}/statement/{fmt}", status_code=status.HTTP_200_OK)
def customer_statement(id: str, fmt: str, startDate: str | None = None, endDate: str | None = None,
                       db: Session = Depends(get_db), _=Depends(require(Module.CUSTOMER, Action.SELECT)),
                       __=Depends(require(Module.FINANCE, Action.SELECT))):
    """Taarifa ya mteja: fmt = pdf au xlsx (ina malipo na madeni - inahitaji ruhusa ya FINANCE)."""
    from fastapi import Response

    from ..core.dao import to_uuid
    from ..core.exceptions import BadRequest
    from .overview import statement_excel, statement_pdf

    if fmt == "pdf":
        content, name = statement_pdf(db, to_uuid(id), startDate, endDate)
        return Response(content, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})
    if fmt == "xlsx":
        content, name = statement_excel(db, to_uuid(id), startDate, endDate)
        return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    raise BadRequest("fmt must be pdf or xlsx")
