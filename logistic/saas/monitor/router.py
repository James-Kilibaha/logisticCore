"""Super admin: kuona kinachoendelea kwa kila kampuni (takwimu, shughuli, kuangalia kama kampuni)."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ...core.audit import client_ip
from ...core.security import get_current_user
from ...db import get_db
from ..admin.model import PlatformAdmin
from ..admin.service import current_admin
from ..company import service as company_service
from . import schema, service

router = APIRouter(tags=["Platform - Monitor"], prefix="/api/platform")
tenant_router = APIRouter(tags=["Activity"], prefix="/api/activity")


@tenant_router.post("/view")
def page_view(request: schema.PageView, http: Request, current_user=Depends(get_current_user)):
    """App inaripoti kila ukurasa unaofunguliwa (super admin anaona kwenye Shughuli)."""
    return service.track_view(current_user, request, client_ip(http))


@router.get("/activity")
def all_activity(company_id: str | None = None, q: str | None = None, module: str | None = None,
                 failed: bool | None = None, kind: str | None = Query(None, pattern="^(views|actions)$"),
                 offset: int = 0, limit: int = Query(100, le=500),
                 db: Session = Depends(get_db), _: PlatformAdmin = Depends(current_admin)):
    """Shughuli zote za kampuni zote - mpya kwanza. kind=views: kurasa walizofungua; kind=actions: vitendo."""
    return service.activity(db, company_id, q, module, failed, offset, limit, kind)


@router.get("/activity/live")
def live_companies(hours: int = Query(24, ge=1, le=720), db: Session = Depends(get_db),
                   _: PlatformAdmin = Depends(current_admin)):
    """Kampuni zilizotumia mfumo ndani ya saa `hours`."""
    return service.live(db, hours)


@router.get("/companies/{company_id}/overview")
def company_overview(company_id: str, db: Session = Depends(get_db), _: PlatformAdmin = Depends(current_admin)):
    return service.overview(db, company_service.get(db, company_id))


@router.post("/companies/{company_id}/impersonate")
def impersonate(company_id: str, http: Request, request: schema.Impersonate | None = None,
                db: Session = Depends(get_db), admin: PlatformAdmin = Depends(current_admin)):
    """Token ya KUANGALIA TU app ya kampuni kama mtumiaji wake (inaandikwa kwenye audit log ya kampuni)."""
    return service.impersonate(db, company_service.get(db, company_id), request or schema.Impersonate(),
                               admin.username, client_ip(http))
