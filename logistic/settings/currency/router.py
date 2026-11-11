from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ...core.enums import Action, Module
from ...core.permission import require, require_any
from ...db import get_db
from . import schema, service

router = APIRouter(tags=["Settings"], prefix="/api/settings")


@router.post("/currency-create", status_code=status.HTTP_201_CREATED)
def create_currency(request: schema.Create, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.PRICE, Action.INSERT))):
    return service.create(db, request, current_user.id)


@router.post("/currency-search", status_code=status.HTTP_200_OK)
def search_currency(request: schema.Filter, db: Session = Depends(get_db),
                    _=Depends(require(Module.PRICE, Action.SELECT))):
    return service.search(db, request)


@router.put("/currency-update", status_code=status.HTTP_200_OK)
def update_currency(request: schema.Update, db: Session = Depends(get_db),
                 _=Depends(require_any((Module.PRICE, Action.UPDATE), (Module.SETTING, Action.UPDATE)))):
    return service.update(db, request)


@router.delete("/currency-rate/{id}", status_code=status.HTTP_200_OK)
def delete_currency_rate(id: str, db: Session = Depends(get_db),
                         _=Depends(require_any((Module.PRICE, Action.DELETE), (Module.SETTING, Action.DELETE)))):
    return service.delete_rate(db, id)


@router.delete("/currency/{id}", status_code=status.HTTP_200_OK)
def delete_currency(id: str, db: Session = Depends(get_db), _=Depends(require_any((Module.PRICE, Action.DELETE), (Module.SETTING, Action.DELETE)))):
    return service.delete(db, id)
