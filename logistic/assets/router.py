from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Fixed assets"], prefix="/api/assets")


@router.get("", status_code=status.HTTP_200_OK)
def list_assets(db: Session = Depends(get_db), _=Depends(require(Module.ACCOUNTING, Action.SELECT))):
    return service.list_all(db)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_asset(request: schema.AssetSave, db: Session = Depends(get_db),
                 current_user=Depends(require(Module.ACCOUNTING, Action.INSERT))):
    return service.save(db, request, current_user.id)


@router.put("/{id}", status_code=status.HTTP_200_OK)
def update_asset(id: str, request: schema.AssetSave, db: Session = Depends(get_db),
                 current_user=Depends(require(Module.ACCOUNTING, Action.UPDATE))):
    return service.save(db, request, current_user.id, id)


@router.post("/{id}/dispose", status_code=status.HTTP_200_OK)
def dispose_asset(id: str, request: schema.Dispose, db: Session = Depends(get_db),
                  current_user=Depends(require(Module.ACCOUNTING, Action.UPDATE))):
    return service.dispose(db, id, request, current_user.id)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
def delete_asset(id: str, db: Session = Depends(get_db), _=Depends(require(Module.ACCOUNTING, Action.DELETE))):
    return service.delete(db, id)
