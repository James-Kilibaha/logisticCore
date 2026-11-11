from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Audit"], prefix="/api/audit")

# Kumbukumbu za vitendo zinaonwa na wenye ruhusa ya kuona "Permission" (msimamizi).


@router.post("/search", status_code=status.HTTP_200_OK, response_model=schema.Page)
def search_audit(request: schema.Search, db: Session = Depends(get_db),
                 _=Depends(require(Module.AUDIT, Action.SELECT))):
    return service.search(db, request)


@router.get("/modules", status_code=status.HTTP_200_OK)
def audit_modules(db: Session = Depends(get_db), _=Depends(require(Module.AUDIT, Action.SELECT))):
    return service.modules(db)
