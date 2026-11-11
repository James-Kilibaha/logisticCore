"""
WhatsApp Business ya kila kampuni (Meta Cloud API).

Kila kampuni inaunganisha akaunti YAKE ya WhatsApp Business:
  1. Phone Number ID + Access Token (+ WABA ID kwa kuona templates) -> zinahifadhiwa kwenye mipangilio ya kampuni
  2. "Jaribu muunganisho" -> Meta inarudisha namba na jina lililothibitishwa (hali inahifadhiwa)
  3. Webhook ya kampuni: /api/public/whatsapp/webhook/<code>  (verify token yake + app secret yake)
     -> Meta inaripoti ujumbe umefika/umesomwa kwa kampuni hiyo.
Ujumbe unatumwa na core/whatsapp.py kwa mipangilio ya kampuni ya request (config.WHATSAPP_*).
"""
import hashlib
import logging
import hmac
import json
import secrets

import requests
from sqlalchemy.orm import Session

from ... import config
from ...core import tenant
from ...core.base_model import utc_now
from ...core.exceptions import BadRequest
from ..company import service as company_service, settings as company_settings
from ..company.model import Company
from . import schema

MASK = "••••••"


def _graph(path: str, token: str, params: dict | None = None) -> dict:
    try:
        r = requests.get(f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}/{path}",
                         headers={"Authorization": f"Bearer {token}"}, params=params or {}, timeout=20)
    except requests.RequestException as error:
        raise BadRequest(f"Meta (WhatsApp) haipatikani: {error}")
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 300:
        message = (body.get("error") or {}).get("message") or r.text[:200]
        raise BadRequest(f"Meta imekataa: {message}")
    return body


def _webhook_url(company: Company) -> str:
    base = company_settings.app_url(company) or (f"https://{config.PLATFORM_DOMAIN}" if config.PLATFORM_DOMAIN else "")
    return f"{base}/api/public/whatsapp/webhook/{company.slug}" if base else f"/api/public/whatsapp/webhook/{company.slug}"


def _ensure_verify_token(db: Session, company: Company) -> str:
    s = dict(company.settings or {})
    if not s.get("WHATSAPP_VERIFY_TOKEN"):
        s["WHATSAPP_VERIFY_TOKEN"] = secrets.token_urlsafe(24)
        company.settings = s
        db.commit()
        db.refresh(company)
    return company.settings["WHATSAPP_VERIFY_TOKEN"]


def view(db: Session, company: Company | None = None) -> dict:
    from ..subscription.service import module_allowed

    company = company or company_service.current(db)
    verify = _ensure_verify_token(db, company)
    s = dict(company.settings or {})
    st = s.get("WHATSAPP_STATUS") or {}
    return {
        "inPlan": module_allowed("WHATSAPP"),
        "enabled": bool(s.get("WHATSAPP_ENABLED")),
        "connected": bool(st.get("ok") and s.get("WHATSAPP_TOKEN") and s.get("WHATSAPP_PHONE_NUMBER_ID")),
        "status": st,
        "phoneNumberId": s.get("WHATSAPP_PHONE_NUMBER_ID") or "",
        "businessAccountId": s.get("WHATSAPP_BUSINESS_ACCOUNT_ID") or "",
        "accessToken": MASK if s.get("WHATSAPP_TOKEN") else "",
        "appSecret": MASK if s.get("WHATSAPP_APP_SECRET") else "",
        "template": s.get("WHATSAPP_TEMPLATE") or "",
        "documentTemplate": s.get("WHATSAPP_DOC_TEMPLATE") or "",
        "imageTemplate": s.get("WHATSAPP_IMAGE_TEMPLATE") or "",
        "language": s.get("WHATSAPP_LANG") or config.default("WHATSAPP_LANG"),
        "webhookUrl": _webhook_url(company),
        "verifyToken": verify,
        "apiVersion": config.WHATSAPP_API_VERSION,
    }


def _check(phone_number_id: str, token: str) -> dict:
    info = _graph(phone_number_id, token,
                  {"fields": "display_phone_number,verified_name,quality_rating,code_verification_status,"
                             "name_status,platform_type"})
    return {"ok": True, "checkedAt": utc_now().isoformat(), "displayPhone": info.get("display_phone_number"),
            "verifiedName": info.get("verified_name"), "quality": info.get("quality_rating"),
            "verification": info.get("code_verification_status"), "nameStatus": info.get("name_status"),
            "error": None}


def connect(db: Session, data: schema.Connect) -> dict:
    """Kuhifadhi taarifa za WhatsApp na kuzijaribu na Meta papo hapo."""
    company = company_service.current(db)
    s = dict(company.settings or {})
    token = s.get("WHATSAPP_TOKEN") if data.accessToken.startswith("••") else data.accessToken.strip()
    if not token or len(token) < 10:
        raise BadRequest("Weka Access Token sahihi (kutoka Meta: System User token)")
    phone_id = data.phoneNumberId.strip()
    status = _check(phone_id, token)  # inakataa (400) kama Meta haikubali token/namba
    s.update({
        "WHATSAPP_PHONE_NUMBER_ID": phone_id,
        "WHATSAPP_TOKEN": token,
        "WHATSAPP_BUSINESS_ACCOUNT_ID": (data.businessAccountId or "").strip() or None,
        "WHATSAPP_TEMPLATE": (data.template or "").strip() or None,
        "WHATSAPP_DOC_TEMPLATE": (data.documentTemplate or "").strip() or None,
        "WHATSAPP_IMAGE_TEMPLATE": (data.imageTemplate or "").strip() or None,
        "WHATSAPP_LANG": (data.language or "").strip() or None,
        "WHATSAPP_ENABLED": bool(data.enabled),
        "WHATSAPP_STATUS": status,
    })
    if data.appSecret is not None and not data.appSecret.startswith("••"):
        s["WHATSAPP_APP_SECRET"] = data.appSecret.strip() or None
    company.settings = {k: v for k, v in s.items() if v is not None}
    db.commit()
    db.refresh(company)
    company_settings.invalidate(company.id)
    return view(db, company)


def test(db: Session) -> dict:
    company = company_service.current(db)
    s = dict(company.settings or {})
    if not (s.get("WHATSAPP_TOKEN") and s.get("WHATSAPP_PHONE_NUMBER_ID")):
        raise BadRequest("WhatsApp bado haijaunganishwa")
    try:
        status = _check(s["WHATSAPP_PHONE_NUMBER_ID"], s["WHATSAPP_TOKEN"])
    except BadRequest as error:
        status = {"ok": False, "checkedAt": utc_now().isoformat(), "error": error.detail}
    s["WHATSAPP_STATUS"] = status
    company.settings = s
    db.commit()
    db.refresh(company)
    company_settings.invalidate(company.id)
    return view(db, company)


def templates(db: Session) -> list[dict]:
    """Templates zilizoidhinishwa kwenye akaunti ya WhatsApp Business ya kampuni (inahitaji WABA ID)."""
    company = company_service.current(db)
    s = dict(company.settings or {})
    if not (s.get("WHATSAPP_TOKEN") and s.get("WHATSAPP_BUSINESS_ACCOUNT_ID")):
        raise BadRequest("Weka WhatsApp Business Account ID (WABA ID) kwanza")
    body = _graph(f"{s['WHATSAPP_BUSINESS_ACCOUNT_ID']}/message_templates", s["WHATSAPP_TOKEN"],
                  {"fields": "name,status,language,category,components", "limit": 200})
    out = []
    for t in body.get("data") or []:
        header = next((c.get("format") for c in t.get("components") or [] if c.get("type") == "HEADER"), None)
        out.append({"name": t.get("name"), "status": t.get("status"), "language": t.get("language"),
                    "category": t.get("category"), "header": header})
    return sorted(out, key=lambda r: (r["status"] != "APPROVED", r["name"] or ""))


def send_test(db: Session, data: schema.TestMessage) -> dict:
    from ...core import whatsapp

    if not whatsapp.configured():
        raise BadRequest("WhatsApp bado haijaunganishwa / haijawashwa")
    company = company_service.current(db)
    text = (data.text or f"Majaribio kutoka {company.name}: WhatsApp imeunganishwa vizuri.").strip()
    message_id = whatsapp.send_text(data.phone, text)
    return {"sent": True, "messageId": message_id}


def disconnect(db: Session) -> dict:
    company = company_service.current(db)
    s = {k: v for k, v in dict(company.settings or {}).items()
         if k not in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_BUSINESS_ACCOUNT_ID",
                      "WHATSAPP_APP_SECRET", "WHATSAPP_STATUS", "WHATSAPP_ENABLED")}
    company.settings = s
    db.commit()
    db.refresh(company)
    company_settings.invalidate(company.id)
    return view(db, company)


def rotate_verify_token(db: Session) -> dict:
    company = company_service.current(db)
    s = dict(company.settings or {})
    s["WHATSAPP_VERIFY_TOKEN"] = secrets.token_urlsafe(24)
    company.settings = s
    db.commit()
    db.refresh(company)
    return view(db, company)


# ------------------------------------------------------------------ webhook ya kampuni (umma, Meta)

def _company_by_slug(db: Session, slug: str) -> Company | None:
    from ..company.dao import CompanyDao

    return CompanyDao(db).by_slug(slug)


def webhook_verify(db: Session, slug: str, params) -> str | None:
    company = _company_by_slug(db, slug)
    expected = (company.settings or {}).get("WHATSAPP_VERIFY_TOKEN") if company else None
    if not expected or params.get("hub.mode") not in (None, "subscribe") or \
            not hmac.compare_digest(str(params.get("hub.verify_token") or ""), expected):
        return None
    return params.get("hub.challenge", "")


def webhook_receive(db: Session, slug: str, raw: bytes, signature: str | None) -> dict | None:
    from ...db import SessionLocal
    from ...sms import dlr

    company = _company_by_slug(db, slug)
    if company is None or company.status != "ACTIVE":
        return None
    secret = (company.settings or {}).get("WHATSAPP_APP_SECRET")
    if secret:  # sahihi ya Meta (X-Hub-Signature-256)
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature or ""):
            return None
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return {"matched": 0}
    with tenant.use_company(company.id, company.slug):  # ripoti zinagusa SMS/WhatsApp za kampuni hii tu
        tdb = SessionLocal()
        try:
            result = dlr.apply_whatsapp(tdb, body)
            from ...whatsapp import inbox

            try:  # majibu/ujumbe kutoka kwa wateja -> inbox
                result = {**(result or {}), "received": inbox.receive(tdb, body)}
            except Exception:
                tdb.rollback()
                logging.getLogger(__name__).exception("WhatsApp inbox failed")
            return result
        finally:
            tdb.close()
