from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Receiver"], prefix="/api/receiver")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_receiver(request: schema.Insert, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.RECEIVE, Action.INSERT))):
    return service.create(db, request, current_user.id)


@router.put("/update", status_code=status.HTTP_200_OK)
def update_receiver(request: schema.Update, db: Session = Depends(get_db),
                    _=Depends(require(Module.RECEIVE, Action.UPDATE))):
    return service.update(db, request)


@router.get("", status_code=status.HTTP_200_OK)
def get_all_receivers(db: Session = Depends(get_db), _=Depends(require(Module.RECEIVE, Action.SELECT))):
    return service.list_all(db)


@router.get("/not-block", status_code=status.HTTP_200_OK)
def get_not_blocked_receivers(db: Session = Depends(get_db), _=Depends(require(Module.RECEIVE, Action.SELECT))):
    return service.list_not_blocked(db)


@router.put("/block", status_code=status.HTTP_200_OK)
def block_receiver(request: schema.Block, db: Session = Depends(get_db),
                   _=Depends(require(Module.RECEIVE, Action.BLOCK))):
    return service.toggle_block(db, request)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
def delete_receiver(id: str, db: Session = Depends(get_db), _=Depends(require(Module.RECEIVE, Action.DELETE))):
    return service.delete(db, id)
