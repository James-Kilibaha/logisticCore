from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core import tenant
from ...core.enums import Action, Module
from ...core.permission import require
from ...db import get_db
from ..admin.model import PlatformAdmin
from ..admin.service import current_admin
from . import schema, service

platform_router = APIRouter(tags=["Platform - Coupons"], prefix="/api/platform/coupons")
company_router = APIRouter(tags=["Company - Subscription"], prefix="/api/company/subscription/coupon")


@platform_router.get("", response_model=list[schema.CouponOut])
def coupons(db: Session = Depends(get_db), _: PlatformAdmin = Depends(current_admin)):
    return service.list_all(db)


@platform_router.post("", response_model=schema.CouponOut)
def create_coupon(request: schema.CouponIn, db: Session = Depends(get_db),
                  admin: PlatformAdmin = Depends(current_admin)):
    request.id = None
    return service.save(db, request, admin.username)


@platform_router.put("", response_model=schema.CouponOut)
def update_coupon(request: schema.CouponIn, db: Session = Depends(get_db),
                  admin: PlatformAdmin = Depends(current_admin)):
    return service.save(db, request, admin.username)


@platform_router.delete("/{coupon_id}")
def delete_coupon(coupon_id: str, db: Session = Depends(get_db), _: PlatformAdmin = Depends(current_admin)):
    return service.delete(db, coupon_id)


@company_router.post("")
def check_coupon(request: schema.CouponCheck, db: Session = Depends(get_db),
                 _=Depends(require(Module.SETTING, Action.SELECT))):
    """Kuhakiki coupon kabla ya kulipa: bei kabla na baada ya punguzo."""
    from ..subscription.service import _plan

    return service.evaluate(db, request.code, tenant.require_company_id(), _plan(db, request.plan_id), request.periods)
