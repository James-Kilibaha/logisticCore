from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from .. import config
from ..core import ratelimit
from ..core.audit import client_ip
from ..core.exceptions import NotFound
from ..db import get_db
from . import service

router = APIRouter(tags=["Public"], prefix="/api/public")


@router.get("/track/{code}", status_code=status.HTTP_200_OK)
def track(code: str, request: Request, db: Session = Depends(get_db)):
    """Bila kuingia. Kizuizi: maombi 30 kwa dakika 5 kwa kila IP."""
    if not config.PUBLIC_TRACKING:
        raise NotFound("Public tracking is disabled")
    ratelimit.hit(f"track:{client_ip(request)}", limit=30, window_seconds=300)
    return service.track(db, code)


@router.get("/info", status_code=status.HTTP_200_OK)
def info():
    return {"name": config.COMPANY_NAME, "phones": config.COMPANY_PHONES, "origin": config.COMPANY_ORIGIN,
            "tracking": config.PUBLIC_TRACKING}


# ------------------------------------------------------- ripoti za kufika kwa ujumbe (gateway -> sisi)
async def _payload(request: Request):
    """JSON, form au query string - kila gateway inatuma kwa namna yake."""
    data = dict(request.query_params)
    if request.method == "POST":
        ctype = request.headers.get("content-type", "")
        try:
            if "json" in ctype:
                body = await request.json()
                if not isinstance(body, dict) or not data:
                    return body
                data.update(body)
            elif "form" in ctype:
                data.update(dict(await request.form()))
        except Exception:  # payload mbovu: tunaacha kama ilivyo
            pass
    return data


@router.api_route("/sms-dlr/{token}", methods=["GET", "POST"], status_code=status.HTTP_200_OK,
                  description="FastHub delivery report (DLR). URL: /api/public/sms-dlr/<SMS_DLR_TOKEN>")
async def sms_dlr(token: str, request: Request, db: Session = Depends(get_db)):
    import hmac

    from ..sms import dlr

    if not config.SMS_DLR_TOKEN or not hmac.compare_digest(token, config.SMS_DLR_TOKEN):
        raise NotFound("Not found")
    return dlr.apply_reports(db, await _payload(request))


@router.get("/whatsapp/webhook", description="Uthibitisho wa webhook ya Meta (hub.challenge)")
def whatsapp_verify(request: Request):
    from fastapi.responses import PlainTextResponse

    q = request.query_params
    if not config.WHATSAPP_VERIFY_TOKEN or q.get("hub.verify_token") != config.WHATSAPP_VERIFY_TOKEN:
        raise NotFound("Not found")
    return PlainTextResponse(q.get("hub.challenge", ""))


@router.post("/whatsapp/webhook", status_code=status.HTTP_200_OK)
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    from ..sms import dlr

    if not config.WHATSAPP_VERIFY_TOKEN:
        raise NotFound("Not found")
    raw = await request.body()
    if config.WHATSAPP_APP_SECRET:  # sahihi ya Meta (X-Hub-Signature-256)
        import hashlib
        import hmac

        expected = "sha256=" + hmac.new(config.WHATSAPP_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("x-hub-signature-256", "")):
            raise NotFound("Not found")
    try:
        import json

        body = json.loads(raw or b"{}")
    except ValueError:
        return {"matched": 0}
    return dlr.apply_whatsapp(db, body)
