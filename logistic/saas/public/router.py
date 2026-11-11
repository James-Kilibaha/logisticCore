from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...core.audit import client_ip
from ...db import get_db
from ..company import schema as company_schema, service as company_service
from ..plan import schema as plan_schema, service as plan_service
from . import service

router = APIRouter(tags=["Public - SaaS"], prefix="/api/public")


@router.get("/branding")
def branding(db: Session = Depends(get_db)):
    """Jina, logo, rangi za kampuni (kwa domain / X-Company / ?company=). `resolved=false` = kampuni haijulikani."""
    return service.branding(db)


@router.get("/branding/logo")
def branding_logo(db: Session = Depends(get_db)):
    path = service.logo_path(db)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/plans", response_model=list[plan_schema.PlanOut])
def public_plans(db: Session = Depends(get_db)):
    return plan_service.list_all(db, public_only=True)


@router.get("/company-check/{slug}")
def company_check(slug: str, db: Session = Depends(get_db)):
    """Usajili: code ya kampuni bado haijachukuliwa?"""
    return company_service.slug_available(db, slug)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(request: company_schema.Signup, http: Request, db: Session = Depends(get_db)):
    """Kampuni mpya inajisajili yenyewe na kupata majaribio (TRIAL_DAYS)."""
    return service.signup(db, request, client_ip(http))
