"""
Kuunganisha FastAPI app: routers, CORS, error handlers, database na scheduler.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .accounting.router import router as accounting_router
from .assets.router import router as assets_router
from .audit.router import router as audit_router
from .payroll.router import router as payroll_router
from .demand.router import router as demand_router
from .auth.router import router as auth_router
from .cashup.router import router as cashup_router
from .core import scheduler
from .core.audit import AuditMiddleware
from .core.exceptions import register_exception_handlers
from .claim.router import router as claim_router
from .customer.router import router as customer_router
from .dashboard.router import router as dashboard_router
from .data_import.router import router as import_router
from .db import init_db, session_scope
from .expense.router import router as expense_router
from .handover.router import router as handover_router
from .invoice.router import router as invoice_router
from .notification.router import router as notification_router
from .popup.router import router as popup_router
from .activity.router import router as my_activity_router
from .package.router import router as package_router
from .payment.router import router as payment_router
from .permission.router import router as permission_router
from .product.router import router as product_router
from .public.router import router as public_router
from .quotation.router import router as quotation_router
from .receiver.router import router as receiver_router
from .role.router import router as role_router
from .saas.admin import service as platform_admin_service
from .saas.admin.router import router as platform_admin_router
from .saas.company import service as company_service
from .saas.company.router import platform_router as platform_company_router, router as company_router
from .saas.middleware import TenantMiddleware
from .saas.audit_log.router import router as platform_audit_router
from .saas.support.router import router as support_router, platform_router as platform_support_router
from .saas.notice.router import router as platform_notice_router
from .saas.coupon.router import platform_router as platform_coupon_router, company_router as company_coupon_router
from .onlinepay.router import (router as online_pay_router, subscription_router as online_sub_router,
                               public_router as online_public_router, platform_router as online_platform_router)
from .saas.audit_log.service import PlatformAuditMiddleware
from .saas.whatsapp.router import router as company_whatsapp_router, webhook_router as whatsapp_webhook_router
from .saas.monitor.router import router as platform_monitor_router, tenant_router as activity_router
from .saas.plan import service as plan_service
from .saas.plan.router import router as platform_plan_router
from .saas.public.router import router as saas_public_router
from .saas.subscription.router import (platform_router as platform_subscription_router,
                                       router as company_subscription_router)
from .report.router import router as report_router
from .settings import routers as settings_routers
from .shipment.router import router as shipment_router
from .sms.router import router as sms_router
from .store.router import router as store_router
from .user.router import router as user_router
from .whatsapp.router import router as whatsapp_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ROUTERS = [
    auth_router, dashboard_router, user_router, permission_router, customer_router, invoice_router, product_router,
    package_router, receiver_router, store_router, payment_router, *settings_routers, expense_router,
    report_router, sms_router, audit_router, handover_router,
    saas_public_router, public_router, role_router, shipment_router, claim_router,
    whatsapp_router, notification_router,
    import_router, cashup_router, quotation_router, popup_router, my_activity_router, platform_audit_router,
    online_pay_router, online_sub_router, online_public_router, online_platform_router,
    platform_coupon_router, company_coupon_router, support_router, platform_support_router, platform_notice_router,
    # SaaS: kampuni (tenant) na admin panel yako (platform)
    company_router, company_subscription_router, activity_router, company_whatsapp_router, whatsapp_webhook_router,
    platform_admin_router, platform_monitor_router, platform_company_router, platform_plan_router,
    platform_subscription_router,
    accounting_router, demand_router, assets_router, payroll_router,
]


def _check_password_hashing() -> None:
    """Nywila zinahashiwa kwa argon2: bila `argon2-cffi` usajili na kuingia vinashindwa (500)."""
    from .core.security import pwd_context

    try:
        pwd_context.hash("check")
    except Exception as error:
        raise RuntimeError("argon2 haipatikani: endesha  pip install -r requirements.txt  "
                           "(au  pip install argon2-cffi==23.1.0 ) kisha washa server upya") from error


def _startup() -> None:
    _check_password_hashing()
    init_db()
    from .db_check import log_problems

    log_problems()  # tofauti za muundo ambazo init_db haiwezi kurekebisha (onyo kwenye log)
    with session_scope() as db:  # (hali ya "system": hakuna kuchuja kwa kampuni)
        platform_admin_service.seed_from_env(db)
        plan_service.seed_defaults(db)
    company_service.adopt_orphans()   # data ya mfumo wa zamani -> DEFAULT_COMPANY_SLUG
    company_service.seed_existing()   # aina mpya za SMS, roles na ruhusa kwa kila kampuni


@asynccontextmanager
async def lifespan(_: FastAPI):
    _startup()
    jobs = scheduler.start() if config.SCHEDULER_ENABLED else None
    yield
    if jobs:
        jobs.shutdown(wait=False)


class SecurityHeadersMiddleware:
    """Headers za usalama kwa kila jibu (na HSTS kama FORCE_HTTPS=true)."""

    _HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    ]

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(self._HEADERS)
                if config.FORCE_HTTPS:
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app() -> FastAPI:
    docs = config.API_DOCS
    application = FastAPI(title=config.APP_TITLE, version="1.0.0", lifespan=lifespan,
                          docs_url="/docs" if docs else None, redoc_url="/redoc" if docs else None,
                          openapi_url="/openapi.json" if docs else None)
    # Mpangilio: ya mwisho kuongezwa ndiyo ya nje kabisa (CORS lazima iwe ya nje).
    application.add_middleware(AuditMiddleware)
    application.add_middleware(PlatformAuditMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)
    # Kampuni ya kila request (lazima iwe nje ya Audit ili audit log ipate kampuni yake)
    application.add_middleware(TenantMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_origin_regex=config.CORS_DEV_REGEX,  # develop: flutter run (localhost:<port yoyote>)
        allow_credentials=False,  # token inatumwa kwenye header, si cookie
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Company", "X-Client", "X-Device"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )
    register_exception_handlers(application)
    for router in ROUTERS:
        application.include_router(router)

    @application.get("/api/health", tags=["Health"])
    def health():
        return {"status": "ok", "env": config.APP_ENV, "platform": config.PLATFORM_NAME}

    if config.SECRET_KEY in ("change-me", "change-me-in-.env") and config.APP_ENV == "production":
        raise RuntimeError("Weka SECRET_KEY ndefu na ya siri kwenye .env kabla ya kuendesha production")
    return application


app = create_app()
