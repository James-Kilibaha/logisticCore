from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..core.security import get_current_user
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Users"], prefix="/api/user")


@router.post("", status_code=status.HTTP_201_CREATED, response_model=schema.DisplayUser)
def create_user(request: schema.UserCreate, db: Session = Depends(get_db),
                _=Depends(require(Module.USER, Action.INSERT))):
    return service.create(db, request)


@router.put("/update", status_code=status.HTTP_200_OK, response_model=schema.DisplayUser)
def update_user(request: schema.UserUpdate, db: Session = Depends(get_db),
                _=Depends(require(Module.USER, Action.UPDATE))):
    return service.update(db, request)


@router.put("/change-password", status_code=status.HTTP_200_OK, response_model=schema.DisplayUser)
def change_password(request: schema.UserChangePass, db: Session = Depends(get_db),
                    _=Depends(require(Module.USER, Action.UPDATE))):
    return service.change_password(db, request)


@router.put("/block", status_code=status.HTTP_200_OK, response_model=schema.DisplayUser)
def block_user(request: schema.UserBlock, db: Session = Depends(get_db),
               _=Depends(require(Module.USER, Action.BLOCK))):
    return service.toggle_block(db, request.id)


@router.get("/me/sessions")
def my_sessions(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Vifaa/browser ulivyoingia navyo hivi karibuni (siku 60)."""
    from datetime import timedelta

    from ..audit.model import AuditLog
    from ..core.base_model import utc_now

    rows = (db.query(AuditLog)
            .filter(AuditLog.user_id == current_user.id, AuditLog.action.in_(["LOGIN", "LOGIN_OTP_OK"]),
                    AuditLog.status_code < 400, AuditLog.created_at >= utc_now() - timedelta(days=60))
            .order_by(AuditLog.created_at.desc()).limit(200).all())
    seen, out = set(), []
    for r in rows:  # kifaa kimoja = safu moja (cha karibuni)
        key = (r.client or "", r.device or "", r.ip or "")
        if key in seen:
            continue
        seen.add(key)
        out.append({"at": r.created_at.isoformat(timespec="seconds") if r.created_at else None, "client": r.client,
                    "device": r.device, "ip": r.ip})
        if len(out) >= 20:
            break
    return out


@router.post("/me/logout-others")
def logout_other_devices(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Kutoka kwenye vifaa vingine vyote: kifaa hiki kinapata tokeni mpya (hakitolewi)."""
    from ..auth.service import _tokens
    from ..core.audit import note
    from .model import User

    user = db.query(User).filter(User.id == current_user.id).first()
    user.tokenVersion = int(user.tokenVersion or 0) + 1
    db.commit()
    db.refresh(user)
    note("Ametoka kwenye vifaa vingine vyote")
    return _tokens(user)


@router.post("/{user_id}/logout-all", status_code=status.HTTP_200_OK, response_model=schema.DisplayUser)
def logout_user_everywhere(user_id: str, db: Session = Depends(get_db),
                           _=Depends(require(Module.USER, Action.UPDATE))):
    """Kumtoa mtumiaji kwenye vifaa vyote (mf. simu imepotea)."""
    return service.logout_everywhere(db, user_id)


@router.put("/two-factor", status_code=status.HTTP_200_OK, response_model=schema.DisplayUser)
def set_two_factor(request: schema.TwoFactor, db: Session = Depends(get_db),
                   _=Depends(require(Module.USER, Action.UPDATE))):
    """Kuwasha / kuzima uthibitisho wa hatua mbili (code ya SMS) kwa mtumiaji."""
    return service.set_two_factor(db, request)


@router.get("/all", response_model=list[schema.UserWithOffice])
def get_all_users(db: Session = Depends(get_db), _=Depends(require(Module.USER, Action.SELECT))):
    return service.list_all(db)


@router.get("/{user_id}", response_model=schema.DisplayUser)
def get_user(user_id: str, db: Session = Depends(get_db), _=Depends(require(Module.USER, Action.SELECT))):
    return service.get(db, user_id)


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
def delete_user(user_id: str, db: Session = Depends(get_db), _=Depends(require(Module.USER, Action.DELETE))):
    return service.delete(db, user_id)



