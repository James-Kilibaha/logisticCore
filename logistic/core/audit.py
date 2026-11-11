"""
Audit log: middleware ya ASGI inayorekodi kila request inayobadilisha data
(POST/PUT/PATCH/DELETE) - nani, lini, nini, kutoka IP gani na matokeo yake.

Service inaweza kuongeza maelezo yanayosomeka kwa:

    from ..core.audit import note
    note("Ankara 0000012 ya Juma imefutwa")
"""
import json
import logging
import re
from contextvars import ContextVar

import anyio
from jose import jwt

from .. import config

logger = logging.getLogger(__name__)

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Njia zinazotumia POST/PUT kusoma tu - hazirekodiwi.
_READ_ONLY = re.compile(r"(search|/get-created-cargo-product|/customer-invoice|^/api/report/|^/api/audit/"
                        r"|^/api/handover/export$|^/api/auth/refresh|^/api/auth/forgot|^/api/login|^/api/public/|^/api/sms$|^/api/notification/read|^/api/activity/)")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_SECRET_KEYS = {"password", "oldPassword", "newPassword", "access_token", "refresh_token", "token", "resetToken",
                "otpToken", "code"}
_MAX_BODY = 16_384

_note: ContextVar[dict | None] = ContextVar("audit_note", default=None)


def note(summary: str) -> None:
    """Maelezo ya kitendo hiki (yanaonekana kwenye audit log)."""
    holder = _note.get()
    if holder is not None:
        holder["summary"] = summary[:500]


def _action(method: str, path: str) -> str:
    p = path.lower()
    for key, action in (("change-password", "PASSWORD"), ("change-status", "STATUS"), ("block", "BLOCK"),
                        ("close-package", "CLOSE"), ("add-product", "ADD"), ("remove-product", "REMOVE"),
                        ("is-correct-package", "RECEIVE"), ("/send", "SEND"), ("generate", "PDF"),
                        ("handover", "HANDOVER"), ("refund", "REFUND"), ("discount", "DISCOUNT"),
                        ("restore", "RESTORE"), ("resolve", "RESOLVE"), ("/document", "SEND"), ("import", "IMPORT")):
        if key in p:
            return action
    return {"POST": "CREATE", "PUT": "UPDATE", "PATCH": "UPDATE", "DELETE": "DELETE"}[method]


def _module(path: str) -> str:
    parts = [x for x in path.split("/") if x][1:]  # bila "api"
    if not parts:
        return "-"
    if parts[0] == "settings" and len(parts) > 1:
        return "settings/" + parts[1].split("-")[0]
    return parts[0]


def _clean(value):
    if isinstance(value, dict):
        return {k: ("***" if k in _SECRET_KEYS else _clean(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value[:50]]
    return value


def _json(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        return None


def _user(headers: dict) -> tuple[str | None, str | None]:
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None, None
    try:
        payload = jwt.decode(auth[7:], config.SECRET_KEY, algorithms=[config.ALGORITHM])
        return payload.get("id"), payload.get("sub")
    except Exception:
        return None, None


def client_ip(scope_or_request) -> str | None:
    """IP ya mteja (inasoma X-Forwarded-For kama server iko nyuma ya nginx)."""
    scope = getattr(scope_or_request, "scope", scope_or_request)
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    if config.BEHIND_PROXY:
        forwarded = headers.get("x-forwarded-for") or headers.get("x-real-ip")
        if forwarded:
            return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else None


def write(**row) -> None:
    from ..audit.model import AuditLog
    from ..db import SessionLocal
    from .client_info import current

    info = current()  # kifaa/programu ya ombi hili (kama haikutajwa)
    row.setdefault("client", info.get("client"))
    row.setdefault("device", (info.get("device") or "")[:120] or None)

    db = SessionLocal()
    try:
        db.add(AuditLog(**row))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Audit log haikuandikwa")
    finally:
        db.close()


class AuditMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from . import client_info

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        device_token = client_info.set_current(headers)  # kwa kumbukumbu zinazoandikwa ndani ya request (mf. login)
        try:
            await self._handle(scope, receive, send, headers)
        finally:
            client_info.reset(device_token)

    async def _handle(self, scope, receive, send, headers):
        if scope["method"] not in _MUTATING or _READ_ONLY.search(scope["path"]):
            await self.app(scope, receive, send)
            return

        is_json = "application/json" in headers.get("content-type", "")
        request_body = bytearray()
        response_body = bytearray()
        state = {"status": 500, "json": False}
        holder: dict = {}
        token = _note.set(holder)

        async def receive_wrapper():
            message = await receive()
            if is_json and message["type"] == "http.request" and len(request_body) < _MAX_BODY:
                request_body.extend(message.get("body", b""))
            return message

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                for k, v in message.get("headers", []):
                    if k.decode().lower() == "content-type" and b"json" in v:
                        state["json"] = True
            elif message["type"] == "http.response.body" and state["json"] and len(response_body) < _MAX_BODY:
                response_body.extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        finally:
            _note.reset(token)
            try:
                await anyio.to_thread.run_sync(lambda: self._record(scope, headers, bytes(request_body),
                                                                    bytes(response_body), state, holder))
            except Exception:
                logger.exception("Audit log haikuandikwa")

    @staticmethod
    def _record(scope, headers, request_body, response_body, state, holder) -> None:
        path, method = scope["path"], scope["method"]
        user_id, username = _user(headers)
        req = _json(request_body)
        res = _json(response_body) if state["json"] else None

        entity = None
        match = _UUID.search(path)
        if match:
            entity = match.group(0)
        elif isinstance(req, dict) and req.get("id"):
            entity = str(req["id"])
        elif isinstance(res, dict) and res.get("id"):
            entity = str(res["id"])

        summary = holder.get("summary")
        if summary is None and state["status"] >= 400 and isinstance(res, dict):
            summary = str(res.get("detail", ""))[:500] or None

        detail = json.dumps(_clean(req), ensure_ascii=False, default=str)[:2000] if req is not None else None
        from .client_info import describe

        info = describe(headers)
        write(user_id=user_id, username=username, module=_module(path), action=_action(method, path),
              method=method, path=path[:300], entity_id=entity, status_code=state["status"],
              ip=client_ip(scope), summary=summary, detail=detail, client=info["client"],
              device=info["device"][:120] or None)
