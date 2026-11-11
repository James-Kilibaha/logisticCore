from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from ..sms.broadcast import RemindOverdue
from . import schema, service

router = APIRouter(tags=["Store"], prefix="/api/store")


@router.get("/overdue", status_code=status.HTTP_200_OK)
def overdue_in_store(db: Session = Depends(get_db), current_user=Depends(require(Module.STORE, Action.SELECT))):
    """Mizigo iliyokaa stoo zaidi ya siku za bure, na gharama ya stoo ya kila mmoja."""
    from ..core.scope import office_scope
    from ..payment import storage

    data = storage.overdue_summary(db, office_scope(db, current_user.id))
    db.commit()  # siku/gharama zilizosasishwa
    return data


@router.post("/overdue/remind", status_code=status.HTTP_200_OK)
def remind_overdue(request: RemindOverdue, db: Session = Depends(get_db),
                   current_user=Depends(require(Module.STORE, Action.UPDATE))):
    """Kumkumbusha mteja (au wote) achukue mzigo uliokaa stoo muda mrefu."""
    from ..core.audit import note
    from ..core.scope import office_scope
    from ..sms import broadcast

    from ..core.permission import need

    if len(request.invoiceIds) != 1:  # wote / wengi = ujumbe kwa wateja wengi
        need(db, current_user.id, Module.BROADCAST, Action.INSERT)
    if (request.channel or "SMS").upper() in ("WHATSAPP", "BOTH"):
        need(db, current_user.id, Module.WHATSAPP, Action.INSERT)
    result = broadcast.remind_overdue(db, request, current_user.id, office_scope(db, current_user.id))
    note(f"Kumbusho la stoo: ankara {result['invoices']} ({result['channel']})")
    return result


@router.post("/generate-invoice", status_code=status.HTTP_200_OK)
def generate_invoice(request: schema.InvoiceStatusRef, db: Session = Depends(get_db),
                     _=Depends(require(Module.STORE, Action.INSERT))):
    return FileResponse(service.generate_invoice_pdf(db, request), media_type="application/pdf")


@router.post("/search", status_code=status.HTTP_200_OK)
def search_invoices(request: schema.Search, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.STORE, Action.SELECT))):
    return service.search_invoices(db, request, current_user.id)


@router.get("/{status}", status_code=status.HTTP_200_OK)
def customers_by_invoice_status(status: str, db: Session = Depends(get_db),
                                _=Depends(require(Module.STORE, Action.SELECT))):
    return service.customers_by_invoice_status(db, status)


@router.get("/account/{status}", status_code=status.HTTP_200_OK)
def customers_by_invoice_account(status: str, db: Session = Depends(get_db),
                                 _=Depends(require(Module.STORE, Action.SELECT))):
    return service.customers_by_invoice_account(db, status)


@router.put("/change-status", status_code=status.HTTP_201_CREATED)
def change_invoice_status(request: schema.UpdateStatus, db: Session = Depends(get_db),
                          _=Depends(require(Module.STORE, Action.UPDATE))):
    return service.change_invoice_status(db, request)


@router.put("/is-correct-package", status_code=status.HTTP_201_CREATED)
def receive_package(request: schema.MarkCollected, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.STORE, Action.UPDATE))):
    return service.receive_package(db, request, current_user.id)


@router.get("/{isCollect}/{isBoxClose}", status_code=status.HTTP_200_OK)
def packages_by_flags(isCollect: bool, isBoxClose: bool, db: Session = Depends(get_db),
                      _=Depends(require(Module.STORE, Action.SELECT))):
    return service.packages_by_flags(db, isCollect, isBoxClose)
