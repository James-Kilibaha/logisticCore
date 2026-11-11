from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.security import get_current_user
from ...db import get_db
from ..admin.model import PlatformAdmin
from ..admin.service import current_admin
from . import schema, service

router = APIRouter(tags=["Company - Msaada"], prefix="/api/support")
platform_router = APIRouter(tags=["Platform - Msaada"], prefix="/api/platform/tickets")


@router.get("")
def my_tickets(status: str | None = Query(None), db: Session = Depends(get_db), _=Depends(get_current_user)):
    return service.mine(db, status)


@router.get("/unread")
def my_unread(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return service.unread_company(db)


@router.post("")
def open_ticket(request: schema.NewTicket, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Kumtumia mtoa huduma tatizo au swali (mtumiaji yeyote wa kampuni)."""
    return service.create(db, request, user)


@router.get("/{ticket_id}")
def ticket(ticket_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return service.view_company(db, ticket_id, mark_read=not getattr(user, "imp", None))


@router.post("/{ticket_id}/reply")
def reply(ticket_id: str, request: schema.Reply, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return service.reply_company(db, ticket_id, request, user)


@router.put("/{ticket_id}/close")
def close(ticket_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return service.close_company(db, ticket_id)


# ------------------------------------------------------------------ super admin

@platform_router.get("")
def tickets(status: str | None = Query(None), company_id: str | None = Query(None), db: Session = Depends(get_db),
            _: PlatformAdmin = Depends(current_admin)):
    return service.admin_list(db, status, company_id)


@platform_router.get("/counts")
def ticket_counts(db: Session = Depends(get_db), _: PlatformAdmin = Depends(current_admin)):
    return service.admin_counts(db)


@platform_router.get("/{ticket_id}")
def ticket_detail(ticket_id: str, db: Session = Depends(get_db), _: PlatformAdmin = Depends(current_admin)):
    return service.admin_view(db, ticket_id)


@platform_router.post("/{ticket_id}/reply")
def ticket_reply(ticket_id: str, request: schema.Reply, db: Session = Depends(get_db),
                 admin: PlatformAdmin = Depends(current_admin)):
    return service.admin_reply(db, ticket_id, request, admin)


@platform_router.put("/{ticket_id}/status")
def ticket_status(ticket_id: str, request: schema.Status, db: Session = Depends(get_db),
                  _: PlatformAdmin = Depends(current_admin)):
    return service.admin_status(db, ticket_id, request.status)
