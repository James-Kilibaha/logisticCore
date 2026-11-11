"""
Mipangilio ya kila kampuni (inasomwa na `config.X` - tazama config.TENANT_KEYS).

Kampuni ikiweka thamani, inatumika badala ya ile ya `.env`. Kumbukumbu (cache) ya sekunde CACHE_SECONDS
inazuia kusoma database kila mara; inafutwa papo hapo kampuni ikibadilisha mipangilio yake.
"""
import threading
import time
import uuid

from ... import config

CACHE_SECONDS = 30

# Mipangilio ambayo kampuni inaweza kubadilisha yenyewe: jina -> aina
EDITABLE: dict[str, type] = {
    "COMPANY_ORIGIN": str,
    "COMPANY_PAYMENT_INFO": str,
    "TIMEZONE": str,
    "PHONE_COUNTRY_CODE": str,
    "SMS_SOURCE_NAME": str,
    "SMS_CLIENT_ID": str,
    "SMS_CLIENT_SECRET": str,
    "SMS_AUTO_SEND": bool,
    "SMS_BALANCE_API": str,
    "SMS_LOW_BALANCE": int,
    "SMS_ITEMS_MAX": int,
    "WHATSAPP_ENABLED": bool,
    "WHATSAPP_TOKEN": str,
    "WHATSAPP_PHONE_NUMBER_ID": str,
    "WHATSAPP_TEMPLATE": str,
    "WHATSAPP_DOC_TEMPLATE": str,
    "WHATSAPP_IMAGE_TEMPLATE": str,
    "WHATSAPP_LANG": str,
    "WHATSAPP_COUNTRY_CODE": str,
    "DAYS_TO_CHARGE": int,
    "STORAGE_CHARGE_USD": float,
    "DEFAULT_CREDIT_LIMIT": float,
    "ETA_AIR_DAYS": int,
    "ETA_SEA_DAYS": int,
    "PUBLIC_TRACKING": bool,
    "REMINDERS_ENABLED": bool,
    "REMINDER_EVERY_DAYS": int,
    "STORAGE_WARN_DAYS": int,
    "STORAGE_ALERT_EVERY_DAYS": int,
    "IMAGE_RETENTION_DAYS": int,
}
# Hazirudishwi wazi kwa app (zinaonyeshwa "••••" tu)
SECRETS = {"SMS_CLIENT_SECRET", "WHATSAPP_TOKEN"}

_lock = threading.Lock()
_cache: dict[uuid.UUID, tuple[float, dict]] = {}


def invalidate(cid=None) -> None:
    with _lock:
        if cid is None:
            _cache.clear()
        else:
            _cache.pop(cid if isinstance(cid, uuid.UUID) else uuid.UUID(str(cid)), None)


def app_url(company) -> str:
    """Anwani ya web app ya kampuni (kwa viungo vya SMS): domain yake au <slug>.<PLATFORM_DOMAIN>."""
    if company.domain:
        return f"https://{company.domain}"
    if config.PLATFORM_DOMAIN:
        return f"https://{company.slug}.{config.PLATFORM_DOMAIN}"
    return ""


def coerce(name: str, value):
    """Thamani kutoka kwa app -> aina sahihi (au None = tumia ya kawaida)."""
    kind = EDITABLE[name]
    if value is None or (isinstance(value, str) and value.strip() == "" and kind is not str):
        return None
    if kind is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind is int:
        return int(float(value))
    if kind is float:
        return float(value)
    text = str(value).strip()
    return text or None


def _compute(company) -> dict:
    s = dict(company.settings or {})
    out: dict = {k: v for k, v in s.items() if k in EDITABLE and v is not None and v != ""}
    out["COMPANY_NAME"] = company.name
    out["COMPANY_PHONES"] = company.phone or ""
    # logo na rangi ya kampuni kwa PDF (ankara, risiti, lebo, ripoti) - core/brand.py
    out["_LOGO_PATH"] = company.logoPath or ""
    out["_PRIMARY"] = company.primaryColor or ""
    url = app_url(company)
    out["PUBLIC_TRACK_URL"] = f"{url}/#/track" if url else ""

    # SMS: gateway ya kampuni yenyewe, au akaunti yako (PLATFORM_SMS_FOR_TENANTS)
    own_sms = bool(s.get("SMS_CLIENT_ID") and s.get("SMS_CLIENT_SECRET"))
    if not own_sms:
        out.pop("SMS_CLIENT_ID", None)
        out.pop("SMS_CLIENT_SECRET", None)
        out.pop("SMS_BALANCE_API", None)  # salio la akaunti yako halionyeshwi kwa kampuni
        out["SMS_BALANCE_API"] = ""
        if not config.PLATFORM_SMS_FOR_TENANTS:
            out["SMS_CLIENT_ID"] = ""
            out["SMS_CLIENT_SECRET"] = ""
    out["_OWN_SMS"] = own_sms

    # WhatsApp ni ya kampuni yenyewe tu (WhatsApp ya .env ni yako)
    wa_token, wa_phone = s.get("WHATSAPP_TOKEN"), s.get("WHATSAPP_PHONE_NUMBER_ID")
    out["WHATSAPP_ENABLED"] = bool(s.get("WHATSAPP_ENABLED") and wa_token and wa_phone)
    out["WHATSAPP_TOKEN"] = wa_token or ""
    out["WHATSAPP_PHONE_NUMBER_ID"] = wa_phone or ""
    for key in ("WHATSAPP_TEMPLATE", "WHATSAPP_DOC_TEMPLATE", "WHATSAPP_IMAGE_TEMPLATE"):
        out[key] = s.get(key) or ""
    return out


def load(cid) -> dict:
    if cid is None:
        return {}
    if not isinstance(cid, uuid.UUID):
        cid = uuid.UUID(str(cid))
    now = time.time()
    with _lock:
        hit = _cache.get(cid)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    from ...core import tenant
    from ...db import SessionLocal
    from .model import Company

    with tenant.system():
        db = SessionLocal()
        try:
            company = db.get(Company, cid)
            values = _compute(company) if company else {}
        finally:
            db.close()
    with _lock:
        _cache[cid] = (now, values)
    return values


def value(cid, name: str):
    return load(cid).get(name)


def public_view(company) -> dict:
    """Mipangilio kwa app ya kampuni (siri zimefichwa) + thamani za kawaida zinazotumika."""
    s = dict(company.settings or {})
    out = {}
    for name in EDITABLE:
        v = s.get(name)
        if name in SECRETS:
            out[name] = "••••••" if v else ""
        else:
            out[name] = v
    defaults = {name: config.default(name) for name in EDITABLE if name not in SECRETS
                and name not in ("SMS_CLIENT_ID", "SMS_BALANCE_API", "WHATSAPP_PHONE_NUMBER_ID")}
    return {"values": out, "defaults": defaults, "ownSms": bool(s.get("SMS_CLIENT_ID") and s.get("SMS_CLIENT_SECRET")),
            "platformSms": config.PLATFORM_SMS_FOR_TENANTS}
