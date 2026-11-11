from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ...core.audit import client_ip
from ...db import get_db
from . import schema, service
from .model import PlatformAdmin

router = APIRouter(tags=["Platform - Admin"], prefix="/api/platform")


@router.post("/login", response_model=schema.LoginResponse)
def login(request: schema.Login, http: Request, db: Session = Depends(get_db)):
    return service.login(db, request, client_ip(http))


@router.post("/login/2fa", response_model=schema.LoginResponse)
def login_2fa(request: schema.TwoFactorLogin, http: Request, db: Session = Depends(get_db)):
    """Hatua ya pili ya kuingia: code ya app ya Authenticator (au code ya dharura)."""
    return service.login_2fa(db, request, client_ip(http))


@router.get("/me/2fa")
def two_factor(admin: PlatformAdmin = Depends(service.current_admin)):
    return service.two_factor_status(admin)


@router.post("/me/2fa/setup")
def two_factor_setup(db: Session = Depends(get_db), admin: PlatformAdmin = Depends(service.current_admin)):
    return service.two_factor_setup(db, admin.id)


@router.post("/me/2fa/enable")
def two_factor_enable(request: schema.TwoFactorCode, http: Request, db: Session = Depends(get_db),
                      admin: PlatformAdmin = Depends(service.current_admin)):
    return service.two_factor_enable(db, admin.id, request, client_ip(http))


@router.post("/me/2fa/disable")
def two_factor_disable(request: schema.TwoFactorConfirm, http: Request, db: Session = Depends(get_db),
                       admin: PlatformAdmin = Depends(service.current_admin)):
    return service.two_factor_disable(db, admin.id, request, client_ip(http))


@router.post("/me/2fa/recovery")
def two_factor_recovery(request: schema.TwoFactorConfirm, http: Request, db: Session = Depends(get_db),
                        admin: PlatformAdmin = Depends(service.current_admin)):
    return service.two_factor_new_recovery(db, admin.id, request, client_ip(http))


@router.post("/admins/{admin_id}/reset-2fa")
def reset_two_factor(admin_id: str, http: Request, db: Session = Depends(get_db),
                     admin: PlatformAdmin = Depends(service.current_admin)):
    return service.reset_two_factor(db, admin_id, admin, client_ip(http))


@router.post("/forgot")
def forgot(request: schema.Forgot, http: Request, db: Session = Depends(get_db)):
    """Umesahau nywila (super admin), hatua ya 1: code kwa SMS/email."""
    return service.forgot(db, request, client_ip(http))


@router.post("/forgot/reset")
def forgot_reset(request: schema.ForgotReset, http: Request, db: Session = Depends(get_db)):
    """Hatua ya 2: code + nywila mpya."""
    return service.forgot_reset(db, request, client_ip(http))


@router.post("/token", include_in_schema=False)
def token_form(http: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Kitufe cha "Authorize" kwenye /docs: username + password za platform admin."""
    res = service.login(db, schema.Login(username=form.username, password=form.password), client_ip(http))
    if res.twoFactorRequired:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Akaunti hii ina 2FA: ingia kupitia app (/#/super-admin)")
    return {"access_token": res.access_token, "token_type": "bearer"}


@router.get("/me", response_model=schema.AdminOut)
def me(admin: PlatformAdmin = Depends(service.current_admin)):
    return admin


@router.put("/password", response_model=schema.LoginResponse)
def change_password(request: schema.ChangePassword, db: Session = Depends(get_db),
                    admin: PlatformAdmin = Depends(service.current_admin)):
    return service.change_password(db, admin.id, request)


@router.get("/reports/revenue")
def revenue_report(months: int = 12, db: Session = Depends(get_db), _: PlatformAdmin = Depends(service.current_admin)):
    """Mapato kwa mwezi, kampuni mpya / zilizoondoka, zinazolipa, na kampuni zilizo hatarini."""
    from . import reports

    return reports.revenue(db, months)


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: PlatformAdmin = Depends(service.current_admin)):
    return service.dashboard(db)


@router.get("/admins", response_model=list[schema.AdminOut])
def list_admins(db: Session = Depends(get_db), _: PlatformAdmin = Depends(service.current_admin)):
    return service.list_admins(db)


@router.post("/admins", response_model=schema.AdminOut, status_code=status.HTTP_201_CREATED)
def create_admin(request: schema.AdminCreate, db: Session = Depends(get_db),
                 _: PlatformAdmin = Depends(service.current_admin)):
    return service.create_admin(db, request)


@router.put("/admins", response_model=schema.AdminOut)
def update_admin(request: schema.AdminUpdate, db: Session = Depends(get_db),
                 admin: PlatformAdmin = Depends(service.current_admin)):
    return service.update_admin(db, request, admin.id)


# ------------------------------------------------------------------ server (backup + hali)

@router.get("/server/health")
def server_health(_: PlatformAdmin = Depends(service.current_admin)):
    from ...core import monitor

    return monitor.details()


@router.post("/server/test-alert")
def server_test_alert(_: PlatformAdmin = Depends(service.current_admin)):
    from ...core import monitor

    sent = monitor.alert([{"key": "test", "message": "Majaribio ya tahadhari - mfumo unafanya kazi"}], force=True)
    return {"sent": sent, "phones": len(monitor.config.ALERT_PHONES), "emails": len(monitor.config.ALERT_EMAILS)}


@router.get("/server/backups")
def list_backups(_: PlatformAdmin = Depends(service.current_admin)):
    from ...backup import service as backups

    return {"status": backups.status(), "items": backups.list_backups()}


@router.post("/server/backups", status_code=status.HTTP_201_CREATED)
def create_backup(_: PlatformAdmin = Depends(service.current_admin)):
    from ...backup import service as backups

    return backups.create_backup(reason="manual")


@router.get("/server/backups/{name}/download")
def download_backup(name: str, _: PlatformAdmin = Depends(service.current_admin)):
    from fastapi.responses import FileResponse

    from ...backup import service as backups

    path = backups.path_of(name)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.delete("/server/backups/{name}")
def delete_backup(name: str, _: PlatformAdmin = Depends(service.current_admin)):
    from ...backup import service as backups

    return backups.delete_backup(name)
