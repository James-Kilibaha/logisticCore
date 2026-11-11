from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require, require_any
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Expenses"], prefix="/api/expenses")

_VIEW = require_any((Module.EXPENSES, Action.SELECT), (Module.ACCOUNTING, Action.SELECT))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_expense(request: schema.Create, db: Session = Depends(get_db),
                   current_user=Depends(require(Module.EXPENSES, Action.INSERT))):
    return service.create(db, request, current_user.id)


@router.put("/update", status_code=status.HTTP_201_CREATED)
def update_expense(request: schema.Update, db: Session = Depends(get_db),
                   current_user=Depends(require_any((Module.EXPENSES, Action.UPDATE),
                                                    (Module.ACCOUNTING, Action.UPDATE)))):
    return service.update(db, request, current_user.id)


@router.post("/search", status_code=status.HTTP_200_OK)
def search_expenses(request: schema.Search, db: Session = Depends(get_db), current_user=Depends(_VIEW)):
    return service.search(db, request, current_user.id)


@router.post("/{id}/approve", status_code=status.HTTP_200_OK)
def approve_expense(id: str, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.ACCOUNTING, Action.UPDATE))):
    return service.approve(db, id, current_user.id)


@router.post("/{id}/reject", status_code=status.HTTP_200_OK)
def reject_expense(id: str, request: schema.Reject, db: Session = Depends(get_db),
                   current_user=Depends(require(Module.ACCOUNTING, Action.UPDATE))):
    return service.reject(db, id, request.reason, current_user.id)


@router.post("/{id}/receipt", status_code=status.HTTP_200_OK)
async def upload_receipt(id: str, file: UploadFile = File(...), db: Session = Depends(get_db),
                         current_user=Depends(require_any((Module.EXPENSES, Action.INSERT),
                                                          (Module.ACCOUNTING, Action.UPDATE)))):
    return service.save_receipt(db, id, file.filename, await file.read(), current_user.id)


@router.get("/{id}/receipt", status_code=status.HTTP_200_OK)
def get_receipt(id: str, db: Session = Depends(get_db), current_user=Depends(_VIEW)):
    return FileResponse(service.receipt_path(db, id, current_user.id))


@router.post("/{id}/pay", status_code=status.HTTP_200_OK)
def pay_expense(id: str, request: schema.Pay, db: Session = Depends(get_db),
                current_user=Depends(require(Module.ACCOUNTING, Action.INSERT))):
    return service.pay(db, id, request, current_user.id)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
def delete_expense(id: str, db: Session = Depends(get_db),
                   current_user=Depends(require_any((Module.EXPENSES, Action.DELETE),
                                                    (Module.ACCOUNTING, Action.DELETE)))):
    return service.delete(db, id, current_user.id)
