"""
WhatsApp Business Cloud API (Meta Graph API).

- Ujumbe wa kawaida unatumwa kama template (WHATSAPP_TEMPLATE) yenye kigezo {{1}} = maandishi.
- PDF (ankara, risiti, hati ya makabidhiano): inapakiwa kama media kisha inatumwa na
  WHATSAPP_DOC_TEMPLATE (header ya DOCUMENT); kama haijawekwa, inatumwa kama "document" ya kawaida
  (inafanya kazi tu ndani ya saa 24 tangu mteja alipoandika).
"""
import logging
import re

import requests

from .. import config
from .exceptions import AppError

logger = logging.getLogger(__name__)


def _base() -> str:
    return f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}/{config.WHATSAPP_PHONE_NUMBER_ID}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}


def configured() -> bool:
    return bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID)


def to_international(phone: str) -> str:
    """0754 111 222 -> 255754111222 (WhatsApp inahitaji namba ya kimataifa bila +)."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0"):
        digits = config.WHATSAPP_COUNTRY_CODE + digits[1:]
    elif len(digits) == 9:
        digits = config.WHATSAPP_COUNTRY_CODE + digits
    return digits


def _param(text: str) -> str:
    # Vigezo vya template haviruhusu mistari mipya, tab, wala nafasi 4+ mfululizo; urefu <= 1024.
    text = re.sub(r"[\r\n\t]+", " | ", text or "")
    return re.sub(r" {4,}", "   ", text).strip()[:1024]


def _post(path: str, **kwargs) -> dict:
    if not configured():
        raise AppError("WhatsApp is not configured (WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID in .env)")
    try:
        response = requests.post(f"{_base()}/{path}", headers=_headers(), timeout=30, **kwargs)
    except requests.RequestException as error:
        raise AppError(f"WhatsApp unreachable: {error}")
    if response.status_code >= 300:
        try:
            detail = response.json().get("error", {}).get("message", response.text[:200])
        except ValueError:
            detail = response.text[:200]
        logger.warning("WhatsApp error %s: %s", response.status_code, detail)
        raise AppError(f"WhatsApp: {detail}")
    return response.json()


def send_text(phone: str, text: str) -> str:
    """Inatuma ujumbe (kupitia template). Inarudisha id ya ujumbe."""
    to = to_international(phone)
    if config.WHATSAPP_TEMPLATE:
        payload = {
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {"name": config.WHATSAPP_TEMPLATE, "language": {"code": config.WHATSAPP_LANG},
                         "components": [{"type": "body", "parameters": [{"type": "text", "text": _param(text)}]}]},
        }
    else:  # bila template: inafanya kazi tu ndani ya dirisha la saa 24
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4096]}}
    body = _post("messages", json=payload)
    return (body.get("messages") or [{}])[0].get("id", "")


def upload_media(content: bytes, filename: str, mime: str) -> str:
    body = _post("media", data={"messaging_product": "whatsapp", "type": mime},
                 files={"file": (filename, content, mime)})
    return body.get("id", "")


def upload_pdf(content: bytes, filename: str) -> str:
    return upload_media(content, filename, "application/pdf")


def image_mime(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    raise AppError("Only JPG and PNG images can be sent on WhatsApp")


def send_image(phone: str, content: bytes, filename: str, caption: str) -> str:
    """Picha + maelezo. Inatumia WHATSAPP_IMAGE_TEMPLATE (nje ya saa 24) au picha ya kawaida (ndani ya saa 24)."""
    if len(content) > 5 * 1024 * 1024:
        raise AppError("Image is larger than 5 MB (WhatsApp limit)")
    media_id = upload_media(content, filename, image_mime(filename))
    to = to_international(phone)
    if config.WHATSAPP_IMAGE_TEMPLATE:
        payload = {
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {"name": config.WHATSAPP_IMAGE_TEMPLATE, "language": {"code": config.WHATSAPP_LANG},
                         "components": [
                             {"type": "header", "parameters": [{"type": "image", "image": {"id": media_id}}]},
                             {"type": "body", "parameters": [{"type": "text", "text": _param(caption)}]}]},
        }
    else:
        payload = {"messaging_product": "whatsapp", "to": to, "type": "image",
                   "image": {"id": media_id, "caption": caption[:1024]}}
    body = _post("messages", json=payload)
    return (body.get("messages") or [{}])[0].get("id", "")


def send_document(phone: str, content: bytes, filename: str, caption: str) -> str:
    media_id = upload_pdf(content, filename)
    to = to_international(phone)
    if config.WHATSAPP_DOC_TEMPLATE:
        payload = {
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {"name": config.WHATSAPP_DOC_TEMPLATE, "language": {"code": config.WHATSAPP_LANG},
                         "components": [
                             {"type": "header", "parameters": [{"type": "document",
                                                                "document": {"id": media_id, "filename": filename}}]},
                             {"type": "body", "parameters": [{"type": "text", "text": _param(caption)}]}]},
        }
    else:
        payload = {"messaging_product": "whatsapp", "to": to, "type": "document",
                   "document": {"id": media_id, "filename": filename, "caption": caption[:1024]}}
    body = _post("messages", json=payload)
    return (body.get("messages") or [{}])[0].get("id", "")


def send_free_text(phone: str, text: str) -> str:
    """Maandishi ya kawaida (si template) - yanakubaliwa na Meta ndani ya saa 24 tangu mteja alipoandika."""
    payload = {"messaging_product": "whatsapp", "to": to_international(phone), "type": "text",
               "text": {"body": text[:4096]}}
    body = _post("messages", json=payload)
    return (body.get("messages") or [{}])[0].get("id", "")


def send_template_text(phone: str, text: str) -> str:
    """Kupitia WHATSAPP_TEMPLATE ({{1}} = maandishi) - inafanya kazi hata nje ya saa 24."""
    if not config.WHATSAPP_TEMPLATE:
        raise AppError("WhatsApp: hakuna template ya ujumbe (WHATSAPP_TEMPLATE) / no message template")
    return send_text(phone, text)


def download_media(media_id: str) -> tuple[bytes, str]:
    """Faili lililotumwa na mteja (picha, PDF, sauti ...): (bytes, mime)."""
    if not configured():
        raise AppError("WhatsApp is not configured")
    try:
        meta = requests.get(f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}/{media_id}",
                            headers=_headers(), timeout=30)
        if meta.status_code >= 300:
            raise AppError("WhatsApp: faili halipatikani tena (Meta inahifadhi kwa siku 30) / media not available")
        info = meta.json()
        response = requests.get(info.get("url", ""), headers=_headers(), timeout=60)
    except requests.RequestException as error:
        raise AppError(f"WhatsApp unreachable: {error}")
    if response.status_code >= 300:
        raise AppError("WhatsApp: faili halikupakuliwa / media download failed")
    return response.content, info.get("mime_type") or response.headers.get("Content-Type", "application/octet-stream")
