from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from ... import config
from ...core import tenant
from ...core.enums import Action, Module
from ...core.permission import require
from ...db import get_db
from ..admin.model import PlatformAdmin
from ..admin.service import current_admin
from ..plan import schema as plan_schema, service as plan_service
from . import schema, service
from .dao import PaymentDao

router = APIRouter(tags=["Company - Subscription"], prefix="/api/company/subscription")
platform_router = APIRouter(tags=["Platform - Subscriptions"], prefix="/api/platform/subscriptions")


# ------------------------------------------------------------------ kampuni yenyewe

@router.get("")
def my_subscription(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.SELECT))):
    cid = tenant.require_company_id()
    return {
        "state": service.state(cid),
        "usage": service.usage(db, cid),
        "history": [schema.SubscriptionOut.model_validate(s).model_dump(mode="json") for s in service.history(db, cid)],
        "payments": [schema.PaymentOut.model_validate(p).model_dump(mode="json")
                     for p in PaymentDao(db).for_company(cid, limit=50)],
        "plans": [plan_schema.PlanOut.model_validate(p).model_dump(mode="json")
                  for p in plan_service.list_all(db, public_only=True)],
        "payTo": config.PLATFORM_PAYMENT_INFO or None,
        "support": {"phone": config.PLATFORM_SUPPORT_PHONE or None, "email": config.PLATFORM_SUPPORT_EMAIL or None},
    }


@router.get("/plan-change")
def plan_change(plan_id: str, periods: int = Query(1, ge=1, le=36), db: Session = Depends(get_db),
                _=Depends(require(Module.SETTING, Action.SELECT))):
    """Kabla ya kulipa: mpango mpya ni mkubwa/mdogo, unaanza lini, siku zinazoongezwa au kufutwa."""
    return service.plan_change(db, tenant.require_company_id(), plan_id, periods)


@router.post("/payment", status_code=status.HTTP_201_CREATED, response_model=schema.PaymentOut)
def submit_payment(request: schema.SubmitPayment, db: Session = Depends(get_db),
                   current_user=Depends(require(Module.SETTING, Action.UPDATE))):
    """Taarifa ya malipo uliyofanya (M-Pesa/benki) - itathibitishwa na mtoa huduma."""
    return service.submit_payment(db, request, submitted_by=current_user.username)


def _pdf(content: bytes, name: str) -> Response:
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@router.get("/payments/{payment_id}/receipt")
def my_receipt(payment_id: str, db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.SELECT))):
    """Risiti (PDF) ya malipo yaliyothibitishwa ya kampuni hii."""
    return _pdf(*service.receipt(db, payment_id, company_id=tenant.require_company_id()))


# ------------------------------------------------------------------ platform admin

@platform_router.get("/payments")
def list_payments(status_: str | None = Query(None, alias="status"), company_id: str | None = None,
                  db: Session = Depends(get_db), _: PlatformAdmin = Depends(current_admin)):
    """Malipo (+ jina la kampuni) - `status=PENDING` = yanayosubiri uthibitisho wako."""
    from ..company.model import Company

    rows = PaymentDao(db).search(status=status_, company_id=company_id)
    names = {c.id: (c.name, c.slug) for c in
             db.query(Company).filter(Company.id.in_({r.company_id for r in rows})).all()} if rows else {}
    out = []
    for row in rows:
        item = schema.PaymentOut.model_validate(row).model_dump(mode="json")
        item["companyName"], item["companySlug"] = names.get(row.company_id, ("-", ""))
        out.append(item)
    return out


@platform_router.get("/payments/{payment_id}/receipt")
def payment_receipt(payment_id: str, db: Session = Depends(get_db), _: PlatformAdmin = Depends(current_admin)):
    return _pdf(*service.receipt(db, payment_id))


@platform_router.get("/plan-change")
def platform_plan_change(company_id: str, plan_id: str, periods: int = Query(1, ge=1, le=36),
                         db: Session = Depends(get_db), _: PlatformAdmin = Depends(current_admin)):
    return service.plan_change(db, company_id, plan_id, periods)


@platform_router.post("/payments", response_model=schema.PaymentOut, status_code=status.HTTP_201_CREATED)
def record_payment(request: schema.RecordPayment, db: Session = Depends(get_db),
                   admin: PlatformAdmin = Depends(current_admin)):
    return service.record_payment(db, request, by=admin.username)


@platform_router.put("/payments/{payment_id}/confirm", response_model=schema.PaymentOut)
def confirm_payment(payment_id: str, request: schema.ReviewPayment | None = None, db: Session = Depends(get_db),
                    admin: PlatformAdmin = Depends(current_admin)):
    return service.confirm_payment(db, payment_id, by=admin.username, note=request.note if request else None)


@platform_router.put("/payments/{payment_id}/reject", response_model=schema.PaymentOut)
def reject_payment(payment_id: str, request: schema.ReviewPayment | None = None, db: Session = Depends(get_db),
                   admin: PlatformAdmin = Depends(current_admin)):
    return service.reject_payment(db, payment_id, by=admin.username, note=request.note if request else None)


@platform_router.post("/extend", response_model=schema.SubscriptionOut)
def extend(request: schema.Extend, db: Session = Depends(get_db), admin: PlatformAdmin = Depends(current_admin)):
    return service.extend(db, request, by=admin.username)


@platform_router.put("/change-plan", response_model=schema.SubscriptionOut)
def change_plan(request: schema.ChangePlan, db: Session = Depends(get_db), _: PlatformAdmin = Depends(current_admin)):
    return service.change_plan(db, request)


@platform_router.put("/{subscription_id}/cancel", response_model=schema.SubscriptionOut)
def cancel(subscription_id: str, db: Session = Depends(get_db), _: PlatformAdmin = Depends(current_admin)):
    return service.cancel(db, subscription_id)


@platform_router.post("/remind-now")
def remind_now(_: PlatformAdmin = Depends(current_admin)):
    """Kuendesha vikumbusho vya subscription sasa hivi (kawaida ni kila siku asubuhi)."""
    return service.remind_expiring()
