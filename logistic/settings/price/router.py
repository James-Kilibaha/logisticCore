from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ...core.enums import Action, Module
from ...core.permission import require, require_any
from ...db import get_db
from . import schema, service

router = APIRouter(tags=["Settings"], prefix="/api/settings")


@router.post("/price-create", status_code=status.HTTP_201_CREATED)
def create_price(request: schema.Create, db: Session = Depends(get_db),
                 current_user=Depends(require(Module.PRICE, Action.INSERT))):
    return service.create(db, request, current_user.id)


@router.post("/price-search", status_code=status.HTTP_200_OK)
def search_price(request: schema.Filter, db: Session = Depends(get_db),
                 _=Depends(require(Module.PRICE, Action.SELECT))):
    return service.search(db, request)


@router.delete("/price/{id}", status_code=status.HTTP_200_OK)
def delete_price(id: str, db: Session = Depends(get_db), _=Depends(require_any((Module.PRICE, Action.DELETE), (Module.SETTING, Action.DELETE)))):
    return service.delete(db, id)
