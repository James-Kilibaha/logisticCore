"""
Kumbukumbu za super admin.

- `record(...)`: kuandika kitendo kimoja (kuingia, 2FA ...).
- `PlatformAuditMiddleware`: kila POST/PUT/DELETE iliyofanikiwa kwenye /api/platform inaandikwa yenyewe,
  pamoja na kampuni iliyoguswa na data iliyotumwa (bila nywila wala siri).
"""
import json
import logging
import re
import uuid

from ... import config

logger = logging.getLogger(__name__)

_SECRET_KEYS = re.compile(r"pass|secret|token|code|otp|key|pin", re.I)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# (method, regex ya njia baada ya /api/platform) -> (action, maelezo)
_ACTIONS = [
    ("POST", r"^/companies$", "COMPANY_CREATE", "Amesajili kampuni"),
    ("PUT", r"^/companies$", "COMPANY_UPDATE", "Amebadilisha taarifa za kampuni"),
    ("PUT", r"^/companies/status$", "COMPANY_STATUS", "Amebadilisha hali ya kampuni (kusimamisha/kuwasha)"),
    ("PUT", r"^/companies/[^/]+/approve$", "COMPANY_APPROVE", "Ameidhinisha kampuni"),
    ("PUT", r"^/companies/[^/]+/reject$", "COMPANY_REJECT", "Amekataa kampuni"),
    ("PUT", r"^/companies/[^/]+/limits$", "COMPANY_LIMITS", "Amebadilisha nafasi za ziada (watumiaji/ofisi/ankara)"),
    ("POST", r"^/companies/[^/]+/logo$", "COMPANY_LOGO", "Amebadilisha logo ya kampuni"),
    ("POST", r"^/companies/[^/]+/reset-password$", "TENANT_PASSWORD", "Amebadilisha nywila ya mtumiaji wa kampuni"),
    ("POST", r"^/companies/[^/]+/export$", "COMPANY_EXPORT", "Amepakua data ya kampuni"),
    ("DELETE", r"^/companies/[^/]+$", "COMPANY_DELETE", "Amefuta kampuni"),
    ("POST", r"^/companies/[^/]+/impersonate$", "VIEW_AS", "Ameingia kama kampuni (kuangalia)"),
    ("POST", r"^/plans$", "PLAN_CREATE", "Ameunda mpango"),
    ("PUT", r"^/plans$", "PLAN_UPDATE", "Amebadilisha mpango"),
    ("DELETE", r"^/plans/[^/]+$", "PLAN_DELETE", "Amefuta mpango"),
    ("POST", r"^/subscriptions/payments$", "PAYMENT_RECORD", "Amerekodi malipo ya subscription"),
    ("PUT", r"^/subscriptions/payments/[^/]+/confirm$", "PAYMENT_CONFIRM", "Amethibitisha malipo"),
    ("PUT", r"^/subscriptions/payments/[^/]+/reject$", "PAYMENT_REJECT", "Amekataa malipo"),
    ("POST", r"^/subscriptions/extend$", "SUBSCRIPTION_EXTEND", "Ameongeza muda wa subscription"),
    ("PUT", r"^/subscriptions/change-plan$", "SUBSCRIPTION_PLAN", "Amebadilisha mpango wa kampuni"),
    ("PUT", r"^/subscriptions/[^/]+/cancel$", "SUBSCRIPTION_CANCEL", "Amesitisha subscription"),
    ("POST", r"^/subscriptions/remind-now$", "REMINDERS", "Ametuma vikumbusho vya subscription"),
    ("POST", r"^/admins$", "ADMIN_CREATE", "Ameongeza msimamizi"),
    ("PUT", r"^/admins$", "ADMIN_UPDATE", "Amebadilisha msimamizi"),
    ("PUT", r"^/password$", "PASSWORD", "Amebadilisha nywila yake"),
    ("POST", r"^/server/backups$", "BACKUP", "Ametengeneza backup"),
    ("DELETE", r"^/server/backups/.+$", "BACKUP_DELETE", "Amefuta backup"),
    ("POST", r"^/server/test-alert$", "TEST_ALERT", "Amejaribu taarifa za server"),
    ("POST", r"^/coupons$", "COUPON_CREATE", "Ameunda coupon ya punguzo"),
    ("PUT", r"^/coupons$", "COUPON_UPDATE", "Amebadilisha coupon"),
    ("DELETE", r"^/coupons/[^/]+$", "COUPON_DELETE", "Amefuta coupon"),
    ("POST", r"^/tickets/[^/]+/reply$", "TICKET_REPLY", "Amejibu tiketi ya msaada"),
    ("PUT", r"^/tickets/[^/]+/status$", "TICKET_STATUS", "Amebadilisha hali ya tiketi"),
    ("POST", r"^/companies/[^/]+/logout-all$", "TENANT_LOGOUT", "Ametoa watumiaji wa kampuni kwenye vifaa vyote"),
]
# zinarekodiwa ndani ya service (zina maelezo bora) au hazina mtumiaji bado
_SKIP = re.compile(r"^/(login|login/2fa|token|forgot|forgot/reset|me/2fa/.*|admins/[^/]+/reset-2fa|notices/read)$")


def record(admin, action: str, summary: str, *, ip: str | None = None, status_code: int = 200, company_id=None,
           method: str = "POST", path: str | None = None, detail: str | None = None) -> None:
    """Inaandika kwa session yake (haiathiri transaction ya ombi). Haitoi kosa."""
    from ...core import tenant
    from ...db import SessionLocal
    from .model import PlatformAuditLog

    try:
        with tenant.system():
            db = SessionLocal()
            try:
                db.add(PlatformAuditLog(
                    admin_id=getattr(admin, "id", None) if admin is not None else None,
                    username=(getattr(admin, "username", None) or "")[:100] or None, action=action[:60],
                    method=method, path=(path or "")[:300] or None, company_id=_as_uuid(company_id),
                    summary=(summary or "")[:500], detail=(detail or None) and detail[:2000], ip=ip,
                    statusCode=status_code))
                db.commit()
            finally:
                db.close()
    except Exception:
        logger.exception("Platform audit write failed")


def _as_uuid(value):
    try:
        return uuid.UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def _clean(value):
    if isinstance(value, dict):
        return {k: ("***" if _SECRET_KEYS.search(str(k)) else _clean(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value[:50]]
    return value


def describe(method: str, sub: str) -> tuple[str, str]:
    for m, pattern, action, text in _ACTIONS:
        if m == method and re.match(pattern, sub):
            return action, text
    return f"{method}", f"{method} {sub}"


class PlatformAuditMiddleware:
    """ASGI middleware: inanasa body na status ya majibu ya /api/platform (POST/PUT/PATCH/DELETE)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope.get("type") == "http" else ""
        method = scope.get("method", "GET")
        if not path.startswith("/api/platform/") and path != "/api/platform":
            return await self.app(scope, receive, send)
        sub = path[len("/api/platform"):] or "/"
        if _SKIP.match(sub) or method == "OPTIONS":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        # majukumu: msimamizi asiye OWNER anaruhusiwa vitendo vya jukumu lake tu
        from anyio import to_thread

        role = await to_thread.run_sync(_role_of, headers.get("authorization", "")[7:])
        if role is not None:
            from ..admin.roles import allowed

            action, _ = describe(method, sub)
            if not allowed(role, method, sub, action):
                return await _deny(send, role)
        if method in ("GET", "HEAD"):
            return await self.app(scope, receive, send)

        chunks: list[bytes] = []
        status = {"code": 500}

        async def recv():
            message = await receive()
            if message.get("type") == "http.request" and len(b"".join(chunks)) < 20000:
                chunks.append(message.get("body", b""))
            return message

        async def snd(message):
            if message.get("type") == "http.response.start":
                status["code"] = message.get("status", 500)
            await send(message)

        await self.app(scope, recv, snd)
        if status["code"] >= 400:
            return
        await to_thread.run_sync(self._write, method, path, sub, headers, b"".join(chunks), status["code"],
                                 _client_ip(scope, headers))

    @staticmethod
    def _write(method, path, sub, headers, body: bytes, code: int, ip: str | None) -> None:
        from jose import jwt

        from ..admin.dao import PlatformAdminDao

        token = headers.get("authorization", "")[7:]
        try:
            payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM]) if token else {}
        except Exception:
            payload = {}
        admin = None
        if payload.get("pid"):
            from ...core import tenant
            from ...db import SessionLocal

            with tenant.system():
                db = SessionLocal()
                try:
                    admin = PlatformAdminDao(db).get(payload["pid"])
                    if admin is not None:
                        db.expunge(admin)
                finally:
                    db.close()
        data = None
        if body and "json" in headers.get("content-type", ""):
            try:
                data = _clean(json.loads(body))
            except ValueError:
                data = None
        company = None
        match = re.match(r"^/companies/([0-9a-fA-F-]{36})", sub)
        if match:
            company = match.group(1)
        elif isinstance(data, dict):
            company = data.get("company_id") or data.get("companyId") or (data.get("id") if sub == "/companies" else None)
        action, text = describe(method, sub)
        detail = json.dumps(data, ensure_ascii=False, default=str) if data else None
        record(admin, action, text, ip=ip, status_code=code, company_id=company, method=method, path=path,
               detail=detail)


def _role_of(token: str) -> str | None:
    """Jukumu la msimamizi wa token hii (None = hakuna token halali - endpoint yenyewe itakataa)."""
    from jose import jwt

    if not token:
        return None
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except Exception:
        return None
    if payload.get("type") != "platform" or not payload.get("pid"):
        return None
    from ...core import tenant
    from ...db import SessionLocal
    from ..admin.dao import PlatformAdminDao

    with tenant.system():
        db = SessionLocal()
        try:
            admin = PlatformAdminDao(db).get(payload["pid"])
            return (admin.role or "OWNER") if admin is not None else None
        finally:
            db.close()


async def _deny(send, role: str) -> None:
    body = json.dumps({"detail": f"Jukumu lako ({role}) haliruhusu kitendo hiki / your role does not allow this",
                       "code": "ROLE_FORBIDDEN"}).encode()
    await send({"type": "http.response.start", "status": 403,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _client_ip(scope, headers) -> str | None:
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else None


def query(db, *, company_id=None, admin=None, action=None, page: int = 1, size: int = 50) -> dict:
    from .model import PlatformAuditLog

    q = db.query(PlatformAuditLog)
    if company_id:
        q = q.filter(PlatformAuditLog.company_id == _as_uuid(company_id))
    if admin:
        q = q.filter(PlatformAuditLog.username.ilike(f"%{admin}%"))
    if action:
        q = q.filter(PlatformAuditLog.action == action)
    total = q.count()
    size = max(1, min(size, 200))
    rows = q.order_by(PlatformAuditLog.created_at.desc()).offset((max(page, 1) - 1) * size).limit(size).all()
    from ..company.model import Company

    ids = {r.company_id for r in rows if r.company_id}
    names = {c.id: (c.name, c.slug) for c in db.query(Company).filter(Company.id.in_(ids)).all()} if ids else {}
    return {"total": total, "page": page, "size": size, "items": [{
        "id": str(r.id), "at": r.created_at.isoformat(timespec="seconds") if r.created_at else None,
        "username": r.username, "action": r.action, "summary": r.summary, "method": r.method, "path": r.path,
        "companyId": str(r.company_id) if r.company_id else None,
        "companyName": names.get(r.company_id, (None, None))[0], "companySlug": names.get(r.company_id, (None, None))[1],
        "detail": r.detail, "ip": r.ip, "statusCode": r.statusCode} for r in rows]}
