from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db import get_db
from ..admin.model import PlatformAdmin
from ..admin.service import current_admin
from . import service

router = APIRouter(tags=["Platform - Notifications"], prefix="/api/platform/notices")


class MarkRead(BaseModel):
    ids: list[str] | None = None
    all: bool = False


@router.get("")
def notices(limit: int = Query(40, ge=1, le=100), pending: bool = True, db: Session = Depends(get_db),
            admin: PlatformAdmin = Depends(current_admin)):
    """Taarifa za msimamizi huyu (kwa jukumu lake) + mambo yanayosubiri hatua."""
    return service.list_for(db, admin, limit=limit, with_pending=pending)


@router.post("/read")
def mark_read(request: MarkRead, db: Session = Depends(get_db), admin: PlatformAdmin = Depends(current_admin)):
    return {"updated": service.mark_read(db, admin, request.ids, request.all)}
