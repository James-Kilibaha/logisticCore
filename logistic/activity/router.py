from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..core.security import TokenData, get_current_user
from ..db import get_db
from . import service

router = APIRouter(tags=["Activity"], prefix="/api/activity")


@router.get("/summary", status_code=status.HTTP_200_OK)
def activity_summary(userId: str | None = None, start: str | None = None, end: str | None = None,
                     db: Session = Depends(get_db), current_user: TokenData = Depends(get_current_user)):
    """Shughuli za mtumiaji (zake mwenyewe; mtumiaji mwingine = ruhusa ya AUDIT tu)."""
    return service.summary(db, current_user.id, userId, start, end)
