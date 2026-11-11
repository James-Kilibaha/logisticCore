from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..core.security import TokenData, get_current_user
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Permission"], prefix="/api/permission")


@router.put("/", status_code=status.HTTP_200_OK, response_model=schema.PermissionList)
def create_permission(request: schema.PermissionCreate, db: Session = Depends(get_db),
                      current_user=Depends(require(Module.PERMISSION, Action.INSERT))):
    return service.create(db, request, current_user.id)


@router.put("/change", status_code=status.HTTP_201_CREATED, response_model=schema.PermissionList)
def update_permission(request: schema.PermissionUpdate, db: Session = Depends(get_db),
                      _=Depends(require(Module.PERMISSION, Action.UPDATE))):
    return service.update(db, request)


@router.get("/me", status_code=status.HTTP_200_OK, response_model=list[schema.PermissionList])
def my_permissions(db: Session = Depends(get_db), current_user: TokenData = Depends(get_current_user)):
    """Ruhusa za mtumiaji aliyeingia - app inazitumia kuonyesha/kuficha menyu."""
    return service.list_for_user(db, current_user.id)


@router.get("/{user_id}", status_code=status.HTTP_200_OK, response_model=list[schema.PermissionList])
def get_permissions(user_id: str, db: Session = Depends(get_db),
                    _=Depends(require(Module.PERMISSION, Action.SELECT))):
    return service.list_for_user(db, user_id)
