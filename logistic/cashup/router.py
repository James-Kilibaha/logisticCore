from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..core.dao import to_uuid
from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import service

router = APIRouter(tags=["CashUp"], prefix="/api/cashup")


@router.get("/expected", status_code=status.HTTP_200_OK)
def expected(day: str | None = None, office: str | None = None, db: Session = Depends(get_db),
             _=Depends(require(Module.CASHUP, Action.SELECT))):
    """Malipo ya siku kwa kila njia (mfumo unatarajia), na kama hesabu imeshafungwa."""
    return service.expected(db, day, to_uuid(office))


@router.post("", status_code=status.HTTP_201_CREATED)
def close_day(request: service.Close, db: Session = Depends(get_db),
              current_user=Depends(require(Module.CASHUP, Action.INSERT))):
    """Kufunga hesabu ya siku: kiasi halisi kwa kila njia."""
    return service.close(db, request, current_user.id)


@router.get("", status_code=status.HTTP_200_OK)
def history(startDate: str | None = None, endDate: str | None = None, office: str | None = None,
            db: Session = Depends(get_db), _=Depends(require(Module.CASHUP, Action.SELECT))):
    return service.history(db, startDate, endDate, to_uuid(office))


@router.get("/{id}/pdf", status_code=status.HTTP_200_OK)
def cashup_pdf(id: str, db: Session = Depends(get_db), _=Depends(require(Module.CASHUP, Action.SELECT))):
    content, name = service.pdf(db, to_uuid(id))
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@router.delete("/{id}", status_code=status.HTTP_200_OK)
def reopen(id: str, db: Session = Depends(get_db), _=Depends(require(Module.CASHUP, Action.DELETE))):
    """Kufungua upya hesabu iliyofungwa (ili ifungwe tena)."""
    return service.reopen(db, to_uuid(id))
