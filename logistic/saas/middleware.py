"""
TenantMiddleware: kila request inajua ni ya kampuni gani kabla ya kufika kwenye router.

Kampuni inatambuliwa kwa mpangilio huu:
  1. token ya mtumiaji (claim `cid`)                    - mtumiaji aliyeingia
  2. `?company=<slug>` (GET tu)                          - viungo vya umma (logo, kufuatilia mzigo)
  3. header `X-Company: <slug>`                          - app ya simu (code ya kampuni)
  4. domain: `ymg.co.tz` (domain yake) au `ymg.<PLATFORM_DOMAIN>`
  5. DEV_COMPANY_SLUG (development tu)

Kisha:
  - kampuni iliyozuiwa (SUSPENDED)   -> 403 kwa kila kitu (isipokuwa branding)
  - subscription imeisha (readOnly)  -> 402 kwa kila kitendo kinachobadilisha data (kusoma kunaruhusiwa)
"""
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass

import anyio
from jose import jwt

from .. import config
from ..core import tenant

logger = logging.getLogger(__name__)

CACHE_SECONDS = 30
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Njia zisizo za kampuni yoyote (hazichujwi)
_SYSTEM = re.compile(r"^(/api/platform(/|$)|/api/public/sms-dlr/|/api/public/whatsapp/|/api/public/payments/|/api/health$|/docs|/redoc"
                     r"|/openapi\.json)")
# Zinaruhusiwa hata kampuni ikiwa imezuiwa
_SUSPENDED_OK = re.compile(r"^/api/public/(branding|plans|info)")
# Zinaruhusiwa hata subscription ikiwa imeisha (kuingia, kulipia, kusoma kwa POST)
_READ_ONLY_OK = re.compile(r"(^/api/login|^/api/auth/|^/api/company/subscription|^/api/notification/read"
                           r"|^/api/public/|search|/get-created-cargo-product|/customer-invoice|^/api/report/"
                           r"|^/api/audit/|/export|/preview|/generate|/pdf|/labels|/manifest|^/api/sms$|^/api/activity/)")


@dataclass(frozen=True)
class CompanyInfo:
    id: uuid.UUID
    slug: str
    status: str
    domain: str | None


_lock = threading.Lock()
_cache: dict[str, tuple[float, CompanyInfo | None]] = {}


def forget(company=None) -> None:
    with _lock:
        _cache.clear()


def _lookup(kind: str, value: str) -> CompanyInfo | None:
    key = f"{kind}:{value}"
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    from ..db import SessionLocal
    from .company.dao import CompanyDao

    with tenant.system():
        db = SessionLocal()
        try:
            dao = CompanyDao(db)
            if kind == "id":
                company = dao.get(value)
            elif kind == "slug":
                company = dao.by_slug(value)
            else:
                company = dao.by_domain(value)
            info = CompanyInfo(company.id, company.slug, company.status, company.domain) if company else None
        finally:
            db.close()
    with _lock:
        _cache[key] = (now, info)
    return info


def _token_payload(scope, headers: dict) -> dict | None:
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        raw = auth[7:]
    else:
        # picha (<img>) haziwezi kutuma header: token inakuja kama ?t=
        from urllib.parse import parse_qs

        values = parse_qs((scope.get("query_string") or b"").decode("latin-1")).get("t") \
            if scope.get("method") == "GET" else None
        if not values:
            return None
        raw = values[0]
    try:
        return jwt.decode(raw, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except Exception:
        return None


def _query_company(scope) -> str | None:
    if scope.get("method") != "GET":
        return None
    from urllib.parse import parse_qs

    values = parse_qs((scope.get("query_string") or b"").decode("latin-1")).get("company")
    return values[0] if values else None


def _host(headers: dict) -> str:
    host = headers.get("x-forwarded-host") if config.BEHIND_PROXY else None
    host = (host or headers.get("host") or "").split(",")[0].strip().lower()
    return host.split(":")[0]


def resolve(scope, headers: dict) -> CompanyInfo | None:
    payload = _token_payload(scope, headers) or {}
    cid = payload.get("cid")
    if cid:
        return _lookup("id", cid)
    # ?company= (GET) ni ya ombi hili peke yake, kwa hiyo inashinda header ya app
    slug = (_query_company(scope) or headers.get("x-company") or "").strip().lower()
    if slug:
        return _lookup("slug", slug)
    host = _host(headers)
    if host and host not in ("localhost", "127.0.0.1") and not re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        info = _lookup("domain", host)
        if info is None and host.startswith("www."):
            info = _lookup("domain", host[4:])
        if info is None and config.PLATFORM_DOMAIN:
            suffix = "." + config.PLATFORM_DOMAIN.lower()
            if host.endswith(suffix):
                sub = host[: -len(suffix)]
                if sub and "." not in sub:
                    info = _lookup("slug", sub)
        if info is not None:
            return info
    if config.DEV_COMPANY_SLUG and config.APP_ENV != "production":
        return _lookup("slug", config.DEV_COMPANY_SLUG)
    return None


async def _reply(send, status: int, detail: str, code: str) -> None:
    body = json.dumps({"detail": detail, "code": code}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class TenantMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if _SYSTEM.match(path):
            token = tenant.set_state(tenant.TenantState(mode="system"))
            try:
                await self.app(scope, receive, send)
            finally:
                tenant.reset(token)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        try:
            info = await anyio.to_thread.run_sync(resolve, scope, headers)
        except Exception:
            logger.exception("Tenant resolution failed")
            info = None

        token = tenant.set_state(tenant.TenantState(mode="tenant", company_id=info.id if info else None,
                                                    slug=info.slug if info else None))
        try:
            if info is not None and info.status != "ACTIVE" and not _SUSPENDED_OK.match(path):
                detail, code = {
                    "PENDING": ("Akaunti ya kampuni hii inasubiri kuthibitishwa na mtoa huduma - utapata SMS "
                                "ikikubaliwa / this company account is awaiting approval", "COMPANY_PENDING"),
                    "REJECTED": ("Ombi la akaunti ya kampuni hii halikukubaliwa - wasiliana na mtoa huduma "
                                 "/ this company registration was not approved", "COMPANY_REJECTED"),
                }.get(info.status, ("Akaunti ya kampuni hii imesimamishwa - wasiliana na mtoa huduma "
                                    "/ this company account is suspended", "COMPANY_SUSPENDED"))
                await _reply(send, 403, detail, code)
                return
            mutating = scope.get("method") in _MUTATING and not _READ_ONLY_OK.search(path)
            if mutating and (_token_payload(scope, headers) or {}).get("ro"):
                # super admin anaangalia kampuni (impersonation): kusoma tu
                await _reply(send, 403, "Unaangalia tu kama super admin - huwezi kubadilisha data ya kampuni "
                                        "/ view-only session", "READ_ONLY_VIEW")
                return
            if info is not None and mutating:
                from .subscription import service as subscriptions

                st = await anyio.to_thread.run_sync(subscriptions.state, info.id)
                if st["readOnly"]:
                    await _reply(send, 402, "Subscription imeisha - mfumo ni wa kusoma tu hadi mlipie "
                                            "/ subscription expired: read-only until payment", "SUBSCRIPTION_EXPIRED")
                    return
            await self.app(scope, receive, send)
        finally:
            tenant.reset(token)
