from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...db import get_db
from ..admin.service import current_admin
from . import service

router = APIRouter(tags=["Platform - Audit"], prefix="/api/platform/audit", dependencies=[Depends(current_admin)])


@router.get("")
def platform_audit(company_id: str | None = Query(None), admin: str | None = Query(None),
                   action: str | None = Query(None), page: int = 1, size: int = 50, db: Session = Depends(get_db)):
    """Vitendo vya wasimamizi wa mfumo (wewe na wasaidizi), vipya kwanza."""
    return service.query(db, company_id=company_id, admin=admin, action=action, page=page, size=size)
