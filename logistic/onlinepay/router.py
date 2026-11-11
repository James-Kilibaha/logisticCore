from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..core import tenant
from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from ..saas.admin.model import PlatformAdmin
from ..saas.admin.service import current_admin
from . import schema, service

router = APIRouter(tags=["Malipo ya simu (AzamPay)"], prefix="/api/online-pay")
subscription_router = APIRouter(tags=["Company - Subscription"], prefix="/api/company/subscription/pay-online")
public_router = APIRouter(tags=["Public - AzamPay callback"], prefix="/api/public/payments")
platform_router = APIRouter(tags=["Platform - Malipo ya simu"], prefix="/api/platform/online-payments")


# ------------------------------------------------------------------ kampuni: akaunti ya AzamPay

@router.get("/settings")
def settings(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.SELECT))):
    return service.settings_view(db)


@router.put("/settings")
def save_settings(request: schema.Settings, db: Session = Depends(get_db),
                  _=Depends(require(Module.SETTING, Action.UPDATE))):
    return service.settings_update(db, request)


@router.delete("/settings")
def clear_settings(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.UPDATE))):
    return service.settings_clear(db)


# ------------------------------------------------------------------ kampuni: kulipisha ankara

@router.post("/invoice")
def pay_invoice(request: schema.PayInvoice, db: Session = Depends(get_db),
                current_user=Depends(require(Module.PAYMENT, Action.INSERT))):
    """Ombi la PIN linatumwa kwenye simu ya mteja; malipo yanarekodiwa yenyewe akithibitisha."""
    return service.start_invoice(db, request, current_user)


@router.get("")
def my_payments(purpose: str | None = Query(None), status: str | None = Query(None), db: Session = Depends(get_db),
                _=Depends(require(Module.PAYMENT, Action.SELECT))):
    return service.list_payments(db, company_id=tenant.require_company_id(), purpose=purpose, status=status)


@router.get("/{payment_id}")
def payment_status(payment_id: str, db: Session = Depends(get_db), _=Depends(require(Module.PAYMENT, Action.SELECT))):
    return service.get(db, payment_id, company_id=tenant.require_company_id())


# ------------------------------------------------------------------ kampuni: subscription kwa simu

@subscription_router.get("")
def subscription_pay_info(_=Depends(require(Module.SETTING, Action.SELECT))):
    from . import azampay

    return {"enabled": service.platform_enabled(), "providers": list(azampay.PROVIDERS.values())}


@subscription_router.post("")
def pay_subscription(request: schema.PaySubscription, db: Session = Depends(get_db),
                     current_user=Depends(require(Module.SETTING, Action.SELECT))):
    return service.start_subscription(db, request, current_user)


@subscription_router.get("/{payment_id}")
def subscription_pay_status(payment_id: str, db: Session = Depends(get_db),
                            _=Depends(require(Module.SETTING, Action.SELECT))):
    return service.get(db, payment_id, company_id=tenant.require_company_id())


# ------------------------------------------------------------------ callback za AzamPay (za siri)

async def _body(http: Request) -> dict:
    try:
        data = await http.json()
    except Exception:
        form = await http.form()
        data = dict(form)
    return data if isinstance(data, dict) else {}


@public_router.post("/azampay/{token}")
async def azampay_platform_callback(token: str, http: Request, db: Session = Depends(get_db)):
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(service.callback, db, await _body(http), token)


@public_router.post("/azampay/{slug}/{token}")
async def azampay_company_callback(slug: str, token: str, http: Request, db: Session = Depends(get_db)):
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(service.callback, db, await _body(http), token, slug)


# ------------------------------------------------------------------ wewe (super admin)

@platform_router.get("")
def platform_payments(purpose: str | None = Query(None), status: str | None = Query(None),
                      company_id: str | None = Query(None), db: Session = Depends(get_db),
                      _: PlatformAdmin = Depends(current_admin)):
    return service.list_payments(db, company_id=company_id, purpose=purpose, status=status)


@platform_router.get("/config")
def platform_config(_: PlatformAdmin = Depends(current_admin)):
    """Hali ya akaunti yako ya AzamPay na URL ya callback ya kuweka kwenye portal ya AzamPay."""
    from .. import config

    return {"enabled": service.platform_enabled(), "env": config.AZAMPAY_ENV, "appName": config.AZAMPAY_APP_NAME,
            "callbackUrl": service.platform_callback_url()}
