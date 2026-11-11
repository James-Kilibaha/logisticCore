from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..core.security import TokenData, get_current_user
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Dashboard"], prefix="/api/dashboard")


@router.get("/summary", status_code=status.HTTP_200_OK, response_model=schema.Summary)
def dashboard_summary(db: Session = Depends(get_db), current_user: TokenData = Depends(get_current_user)):
    """
    Takwimu za jumla (za ofisi yake tu kama mtumiaji amefungiwa ofisi moja).
    Pesa (madeni, malipo, matumizi, mapato) zinaonekana kwa mwenye ruhusa ya DASHBOARD (select) tu.
    """
    from ..core.enums import Action, Module
    from ..permission.dao import PermissionDao

    data = service.summary(db, current_user.id)
    if not PermissionDao(db).has(current_user.id, Module.DASHBOARD.value, Action.SELECT.value):
        data = service.hide_money(data)
    return data
