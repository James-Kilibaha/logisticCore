from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require, require_any
from ..core.security import TokenData, get_current_user
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Cost demands"], prefix="/api/demands")

_ADMIN = require_any((Module.ACCOUNTING, Action.UPDATE), (Module.SETTING, Action.UPDATE))


@router.get("/mine", status_code=status.HTTP_200_OK)
def mine(db: Session = Depends(get_db), current_user: TokenData = Depends(get_current_user)):
    """Madai yanayonihusu + kama kazi zangu zimezuiwa (app inaonyesha pop-up)."""
    return service.mine(db, current_user.id)


@router.get("", status_code=status.HTTP_200_OK)
def list_demands(status: str | None = None, db: Session = Depends(get_db),
                 current_user=Depends(require_any((Module.ACCOUNTING, Action.SELECT), (Module.PROFIT, Action.SELECT)))):
    return service.list_all(db, current_user.id, status)


@router.post("/fill-many", status_code=status.HTTP_200_OK)
def fill_many(request: schema.FillMany, db: Session = Depends(get_db),
              current_user: TokenData = Depends(get_current_user)):
    return service.fill_many(db, request, current_user.id)


@router.post("/{id}/fill", status_code=status.HTTP_200_OK)
def fill(id: str, request: schema.Fill, db: Session = Depends(get_db),
         current_user: TokenData = Depends(get_current_user)):
    return service.fill(db, id, request.costs, current_user.id)


@router.post("/{id}/no-cost", status_code=status.HTTP_200_OK)
def no_cost(id: str, request: schema.Reason, db: Session = Depends(get_db),
            current_user: TokenData = Depends(get_current_user)):
    return service.no_cost(db, id, request.reason, current_user.id)


@router.post("/{id}/waive", status_code=status.HTTP_200_OK)
def waive(id: str, request: schema.Reason, db: Session = Depends(get_db),
          current_user=Depends(require(Module.ACCOUNTING, Action.UPDATE))):
    return service.waive(db, id, request.reason, current_user.id)


@router.get("/rules", status_code=status.HTTP_200_OK)
def rules(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return service.rules(db)


@router.put("/rules/{trigger}", status_code=status.HTTP_200_OK)
def save_rule(trigger: str, request: schema.RuleSave, db: Session = Depends(get_db), _=Depends(_ADMIN)):
    return service.save_rule(db, trigger, request)
