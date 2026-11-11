from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ...core.enums import Action, Module
from ...core.permission import require
from ...db import get_db
from . import schema, service

router = APIRouter(tags=["Settings"], prefix="/api/settings")


@router.get("/sms-set-create", status_code=status.HTTP_201_CREATED, response_model=list[schema.SmsSet])
def create_sms_set(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.INSERT))):
    return service.create_missing(db)


@router.get("/sms-set-search", status_code=status.HTTP_200_OK, response_model=list[schema.SmsSet])
def search_sms_set(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.SELECT))):
    return service.list_all(db)


@router.put("/sms-set-update/{id}", status_code=status.HTTP_200_OK, response_model=schema.SmsSet)
def toggle_sms_set(id: str, db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.UPDATE))):
    return service.toggle(db, id)
