from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.security import TokenData, get_current_user
from ..db import get_db
from . import service

router = APIRouter(tags=["Notifications"], prefix="/api/notification")


class MarkRead(BaseModel):
    ids: list[UUID] = []
    all: bool = False


@router.get("", status_code=status.HTTP_200_OK)
def my_notifications(unreadOnly: bool = False, limit: int = 30, db: Session = Depends(get_db),
                     current_user: TokenData = Depends(get_current_user)):
    return service.list_for(db, current_user.id, unreadOnly, min(max(limit, 1), 100))


@router.put("/read", status_code=status.HTTP_200_OK)
def mark_read(request: MarkRead, db: Session = Depends(get_db), current_user: TokenData = Depends(get_current_user)):
    return {"updated": service.mark_read(db, current_user.id, request.ids, request.all)}
