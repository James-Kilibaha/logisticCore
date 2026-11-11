from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Invoice"], prefix="/api/invoice")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_invoice(request: schema.Create, db: Session = Depends(get_db),
                   current_user=Depends(require(Module.INVOICE, Action.INSERT))):
    return service.create(db, request, current_user.id)


@router.get("", status_code=status.HTTP_200_OK)
def get_invoices(db: Session = Depends(get_db), _=Depends(require(Module.INVOICE, Action.SELECT))):
    return service.list_all(db)


@router.get("/invoice-by-status/{status}", status_code=status.HTTP_200_OK)
def get_invoices_by_status(status: str, db: Session = Depends(get_db),
                           _=Depends(require(Module.INVOICE, Action.SELECT))):
    return service.by_status(db, status)


@router.get("/{customerId}", status_code=status.HTTP_200_OK)
def get_customer_invoices(customerId: str, db: Session = Depends(get_db),
                          _=Depends(require(Module.INVOICE, Action.SELECT))):
    return service.by_customer(db, customerId)


@router.put("/change-status", status_code=status.HTTP_201_CREATED)
def change_invoice_status(request: schema.UpdateStatus, db: Session = Depends(get_db),
                          _=Depends(require(Module.INVOICE, Action.UPDATE))):
    return service.change_status(db, request)


@router.post("/get-created-cargo-product", status_code=status.HTTP_200_OK)
def get_created_cargo_product(request: schema.CustomerStatus, db: Session = Depends(get_db),
                              _=Depends(require(Module.INVOICE, Action.SELECT))):
    return service.created_cargo_products(db, request)


@router.put("/customer-invoice", status_code=status.HTTP_200_OK)
def get_customer_invoice(request: schema.CustomerStatus, db: Session = Depends(get_db),
                         _=Depends(require(Module.INVOICE, Action.SELECT))):
    return service.customer_invoices(db, request)


@router.put("/block", status_code=status.HTTP_200_OK)
def block_invoice(request: schema.Block, db: Session = Depends(get_db),
                  _=Depends(require(Module.INVOICE, Action.BLOCK))):
    return service.block(db, request)


@router.delete("/blocked", status_code=status.HTTP_200_OK)
def delete_blocked_invoices(db: Session = Depends(get_db),
                            _=Depends(require(Module.INVOICE, Action.DELETE))):
    return service.delete_blocked(db)


@router.delete("/{invoiceId}", status_code=status.HTTP_200_OK)
def delete_invoice(invoiceId: str, db: Session = Depends(get_db),
                   _=Depends(require(Module.INVOICE, Action.DELETE))):
    return service.delete(db, invoiceId)


@router.post("/search", status_code=status.HTTP_200_OK)
def search_invoices(request: schema.Search, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.INVOICE, Action.SELECT))):
    return service.search(db, request, current_user.id)


@router.put("/office", status_code=status.HTTP_200_OK)
def set_invoice_office(request: schema.SetOffice, db: Session = Depends(get_db),
                       current_user=Depends(require(Module.INVOICE, Action.UPDATE))):
    return service.set_office(db, request, current_user.id)


@router.post("/generate-invoice", status_code=status.HTTP_200_OK)
def generate_invoice(request: schema.InvoiceStatusRef, db: Session = Depends(get_db),
                     _=Depends(require(Module.INVOICE, Action.INSERT))):
    return FileResponse(service.generate_pdf(db, request), media_type="application/pdf")
