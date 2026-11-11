from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Roles"], prefix="/api/role")


@router.get("", status_code=status.HTTP_200_OK, response_model=list[schema.Display])
def list_roles(db: Session = Depends(get_db), _=Depends(require(Module.PERMISSION, Action.SELECT))):
    return service.list_all(db)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=schema.Display)
def create_role(request: schema.Save, db: Session = Depends(get_db),
                _=Depends(require(Module.PERMISSION, Action.INSERT))):
    return service.create(db, request)


@router.put("/assign", status_code=status.HTTP_200_OK)
def assign_role(request: schema.Assign, db: Session = Depends(get_db),
                _=Depends(require(Module.PERMISSION, Action.UPDATE))):
    return service.assign(db, request)


@router.put("/{role_id}", status_code=status.HTTP_200_OK, response_model=schema.Display)
def update_role(role_id: str, request: schema.Save, db: Session = Depends(get_db),
                _=Depends(require(Module.PERMISSION, Action.UPDATE))):
    return service.update(db, role_id, request)


@router.delete("/{role_id}", status_code=status.HTTP_200_OK)
def delete_role(role_id: str, db: Session = Depends(get_db), _=Depends(require(Module.PERMISSION, Action.DELETE))):
    return service.delete(db, role_id)
