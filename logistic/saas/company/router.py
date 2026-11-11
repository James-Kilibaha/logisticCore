"""
- /api/platform/companies/... : wewe (platform admin) - kampuni zote
- /api/company/...            : kampuni iliyoingia - wasifu, logo, mipangilio yake
"""
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from ...core.enums import Action, Module
from ...core.permission import require
from ...core.security import get_current_user
from ...db import get_db
from ..admin import schema as admin_schema, service as admin_service
from ..admin.model import PlatformAdmin
from . import schema, service

platform_router = APIRouter(tags=["Platform - Companies"], prefix="/api/platform/companies")
router = APIRouter(tags=["Company"], prefix="/api/company")


# ------------------------------------------------------------------ platform admin

@platform_router.get("")
def search_companies(q: str | None = None, status_: str | None = Query(None, alias="status"),
                     offset: int = 0, limit: int = Query(50, le=500), db: Session = Depends(get_db),
                     _: PlatformAdmin = Depends(admin_service.current_admin)):
    from ..subscription import service as subscriptions
    from .dao import CompanyDao

    rows, total = CompanyDao(db).search(q, status_, offset, limit)
    items = []
    for company in rows:
        out = schema.CompanyAdminOut.model_validate(company).model_dump(mode="json")
        out["subscription"] = subscriptions.compute(db, company.id)
        items.append(out)
    return {"total": total, "items": items}


@platform_router.post("", status_code=status.HTTP_201_CREATED, response_model=schema.CompanyAdminOut)
def create_company(request: schema.CompanyCreate, db: Session = Depends(get_db),
                   admin: PlatformAdmin = Depends(admin_service.current_admin)):
    return service.create(db, request, source="ADMIN", by=admin.username)


@platform_router.get("/slug-check/{slug}")
def slug_check(slug: str, db: Session = Depends(get_db), _: PlatformAdmin = Depends(admin_service.current_admin)):
    return service.slug_available(db, slug)


@platform_router.get("/{company_id}")
def company_detail(company_id: str, db: Session = Depends(get_db),
                   _: PlatformAdmin = Depends(admin_service.current_admin)):
    from ..subscription import schema as sub_schema, service as subscriptions
    from ..subscription.dao import PaymentDao
    from . import settings as company_settings

    company = service.get(db, company_id)
    return {
        "company": schema.CompanyAdminOut.model_validate(company).model_dump(mode="json"),
        "branding": service.branding(company),
        "settings": company_settings.public_view(company),
        "subscription": subscriptions.compute(db, company.id),
        "usage": subscriptions.usage(db, company.id),
        "history": [sub_schema.SubscriptionOut.model_validate(s).model_dump(mode="json")
                    for s in subscriptions.history(db, company.id)],
        "payments": [sub_schema.PaymentOut.model_validate(p).model_dump(mode="json")
                     for p in PaymentDao(db).for_company(company.id)],
        "users": admin_service.tenant_users(db, company.id),
        "whatsapp": {
            "enabled": bool((company.settings or {}).get("WHATSAPP_ENABLED")),
            **{k: v for k, v in ((company.settings or {}).get("WHATSAPP_STATUS") or {}).items()
               if k in ("ok", "displayPhone", "verifiedName", "quality", "checkedAt", "error")},
        },
    }


@platform_router.put("", response_model=schema.CompanyAdminOut)
def update_company(request: schema.CompanyUpdate, db: Session = Depends(get_db),
                   _: PlatformAdmin = Depends(admin_service.current_admin)):
    return service.update(db, request)


@platform_router.put("/status", response_model=schema.CompanyAdminOut)
def set_status(request: schema.StatusUpdate, db: Session = Depends(get_db),
               _: PlatformAdmin = Depends(admin_service.current_admin)):
    return service.set_status(db, request)


@platform_router.put("/{company_id}/approve", response_model=schema.CompanyAdminOut)
def approve_company(company_id: str, request: schema.Approve | None = None, db: Session = Depends(get_db),
                    admin: PlatformAdmin = Depends(admin_service.current_admin)):
    """Kuthibitisha kampuni iliyojisajili (PENDING -> ACTIVE) - majaribio yanaanza leo."""
    return service.approve(db, company_id, request or schema.Approve(), admin.username)


@platform_router.put("/{company_id}/reject", response_model=schema.CompanyAdminOut)
def reject_company(company_id: str, request: schema.Reject | None = None, db: Session = Depends(get_db),
                   admin: PlatformAdmin = Depends(admin_service.current_admin)):
    return service.reject(db, company_id, request or schema.Reject(), admin.username)


@platform_router.put("/{company_id}/limits", response_model=schema.CompanyAdminOut)
def set_limits(company_id: str, request: schema.LimitsUpdate, db: Session = Depends(get_db),
               _: PlatformAdmin = Depends(admin_service.current_admin)):
    """Nafasi za ziada juu ya mpango: watumiaji, ofisi, ankara kwa mwezi (0 = kama mpango)."""
    return service.set_limits(db, company_id, request)


@platform_router.post("/{company_id}/logo", response_model=schema.CompanyAdminOut)
async def upload_company_logo(company_id: str, file: UploadFile = File(...), db: Session = Depends(get_db),
                              _: PlatformAdmin = Depends(admin_service.current_admin)):
    content = await file.read()
    return service.save_logo(db, file.filename, content, company=service.get(db, company_id))


@platform_router.post("/{company_id}/reset-password")
def reset_tenant_password(company_id: str, request: admin_schema.ResetTenantPassword, db: Session = Depends(get_db),
                          _: PlatformAdmin = Depends(admin_service.current_admin)):
    service.get(db, company_id)
    return admin_service.reset_tenant_password(db, company_id, request)


@platform_router.delete("/{company_id}")
def delete_company(company_id: str, confirm: str = Query(..., description="slug ya kampuni"),
                   db: Session = Depends(get_db), _: PlatformAdmin = Depends(admin_service.current_admin)):
    return service.delete(db, company_id, confirm)


def _zip(path: str, name: str) -> FileResponse:
    import os

    return FileResponse(path, media_type="application/zip", filename=name,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.remove(path)))


@platform_router.post("/{company_id}/logout-all")
def logout_company_users(company_id: str, db: Session = Depends(get_db),
                         _: PlatformAdmin = Depends(admin_service.current_admin)):
    """Kuwatoa watumiaji WOTE wa kampuni kwenye vifaa vyote (mf. akaunti imeingiliwa)."""
    from sqlalchemy import text

    from ...core import tenant

    company = service.get(db, company_id)
    with tenant.system():
        n = db.execute(text('UPDATE users SET "tokenVersion" = COALESCE("tokenVersion", 0) + 1 '
                            "WHERE company_id = :cid"), {"cid": company.id}).rowcount
        db.commit()
    return {"users": n}


@platform_router.get("/{company_id}/export")
def export_company(company_id: str, http: Request, db: Session = Depends(get_db),
                   admin: PlatformAdmin = Depends(admin_service.current_admin)):
    """Data yote ya kampuni (ZIP: JSON + CSV kwa kila table + picha/PDF zake) - bila nywila wala siri."""
    from ...core.audit import client_ip
    from ..audit_log import record
    from . import export

    company = service.get(db, company_id)
    path, name, counts = export.build(db, company)
    record(admin, "COMPANY_EXPORT", f"Amepakua data ya kampuni {company.name}", ip=client_ip(http), method="GET",
           company_id=company.id, path=f"/api/platform/companies/{company_id}/export",
           detail=f"safu {sum(v for k, v in counts.items() if not k.startswith('_'))}, faili {counts.get('_files', 0)}")
    return _zip(path, name)


# ------------------------------------------------------------------ kampuni yenyewe

@router.get("/onboarding")
def onboarding(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.SELECT))):
    """Hatua za kwanza za kampuni (logo, ofisi, bei, watumiaji, SMS, mteja na ankara ya kwanza ...)."""
    from . import onboarding as ob

    return ob.steps(db, service.current(db))


@router.put("/onboarding/hide")
def hide_onboarding(hidden: bool = True, db: Session = Depends(get_db),
                    _=Depends(require(Module.SETTING, Action.UPDATE))):
    from . import onboarding as ob

    return ob.hide(db, service.current(db), hidden)


@router.get("/export")
def export_my_company(http: Request, db: Session = Depends(get_db),
                      current_user=Depends(require(Module.SETTING, Action.UPDATE))):
    """Data yote ya kampuni yetu (ZIP) - backup yetu wenyewe au kuhamisha. Inafanya kazi hata subscription ikiisha."""
    from ...core import audit
    from . import export

    company = service.current(db)
    path, name, counts = export.build(db, company)
    rows = sum(v for k, v in counts.items() if not k.startswith("_"))
    audit.write(user_id=current_user.id, username=getattr(current_user, "username", None), module="company",
                action="EXPORT", method="GET", path="/api/company/export", entity_id=None, status_code=200,
                ip=audit.client_ip(http), summary=f"Amepakua data yote ya kampuni ({rows} safu, "
                                                  f"faili {counts.get('_files', 0)})", detail=None)
    return _zip(path, name)


@router.get("")
def my_company(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.SELECT))):
    """Wasifu, mipangilio, subscription na matumizi ya kampuni."""
    return service.profile(db)


@router.get("/me")
def my_company_light(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Kwa kila mtumiaji (bila ruhusa ya mipangilio): branding + hali ya subscription + moduli za mpango."""
    from ..subscription import service as subscriptions

    company = service.current(db)
    return {"branding": service.branding(company), "subscription": subscriptions.state(company.id)}


@router.put("/profile", response_model=schema.CompanyOut)
def update_profile(request: schema.ProfileUpdate, db: Session = Depends(get_db),
                   _=Depends(require(Module.SETTING, Action.UPDATE))):
    return service.update_profile(db, request)


@router.put("/settings")
def update_settings(request: schema.SettingsUpdate, db: Session = Depends(get_db),
                    _=Depends(require(Module.SETTING, Action.UPDATE))):
    return service.update_settings(db, request)


@router.post("/logo", response_model=schema.CompanyOut)
async def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db),
                      _=Depends(require(Module.SETTING, Action.UPDATE))):
    content = await file.read()
    return service.save_logo(db, file.filename, content)


@router.delete("/logo", response_model=schema.CompanyOut)
def delete_logo(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.UPDATE))):
    return service.remove_logo(db)
