from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ...core.enums import Action, Module
from ...core.permission import require
from ...db import get_db
from . import schema, service

router = APIRouter(tags=["Settings"], prefix="/api/settings")


@router.post("/institute-create", status_code=status.HTTP_201_CREATED)
def create_institute(request: schema.Create, db: Session = Depends(get_db),
                     current_user=Depends(require(Module.SETTING, Action.INSERT))):
    return service.create(db, request, current_user.id)


@router.post("/institute-search", status_code=status.HTTP_200_OK)
def search_institute(request: schema.Filter, db: Session = Depends(get_db),
                     _=Depends(require(Module.SETTING, Action.SELECT))):
    return service.search(db, request)


@router.put("/institute-update", status_code=status.HTTP_200_OK)
def update_institute(request: schema.Update, db: Session = Depends(get_db),
                 _=Depends(require(Module.SETTING, Action.UPDATE))):
    return service.update(db, request)


@router.delete("/institute/{id}", status_code=status.HTTP_200_OK)
def delete_institute(id: str, db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.DELETE))):
    return service.delete(db, id)
