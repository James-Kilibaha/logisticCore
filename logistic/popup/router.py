from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..core.security import TokenData, get_current_user
from ..db import get_db
from . import service

router = APIRouter(tags=["Popup alerts"], prefix="/api/popup")


class RuleUpdate(BaseModel):
    kind: str
    enabled: bool | None = None
    afterDays: int | None = Field(None, ge=0, le=365)
    everyMinutes: int | None = Field(None, ge=5, le=10080)


@router.get("/due", status_code=status.HTTP_200_OK)
def due(db: Session = Depends(get_db), current_user: TokenData = Depends(get_current_user)):
    """Taarifa za pop-up za mtumiaji huyu (wadaiwa, mizigo stoo muda mrefu, mabox yaliyo wazi, ...)."""
    return service.due(db, current_user.id)


@router.get("/rules", status_code=status.HTTP_200_OK)
def rules(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.SELECT))):
    return service.rules(db)


@router.put("/rules", status_code=status.HTTP_200_OK)
def update_rules(request: list[RuleUpdate], db: Session = Depends(get_db),
                 _=Depends(require(Module.SETTING, Action.UPDATE))):
    return service.update_rules(db, [r.model_dump() for r in request])
