"""WhatsApp Business ya kampuni: kuunganisha, kujaribu, templates + webhook yake ya Meta."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ...core.enums import Action, Module
from ...core.exceptions import NotFound
from ...core.permission import require
from ...db import get_db
from ..subscription.service import ensure_module
from . import schema, service

router = APIRouter(tags=["Company - WhatsApp"], prefix="/api/company/whatsapp")
webhook_router = APIRouter(tags=["Public - WhatsApp webhook"], prefix="/api/public/whatsapp")


@router.get("")
def get_connection(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.SELECT))):
    """Hali ya muunganisho + Webhook URL na verify token za kuweka kwenye Meta."""
    return service.view(db)


@router.put("")
def connect(request: schema.Connect, db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.UPDATE))):
    ensure_module("WHATSAPP")
    return service.connect(db, request)


@router.post("/test")
def test_connection(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.UPDATE))):
    return service.test(db)


@router.get("/templates")
def list_templates(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.SELECT))):
    return service.templates(db)


@router.post("/test-message")
def test_message(request: schema.TestMessage, db: Session = Depends(get_db),
                 _=Depends(require(Module.SETTING, Action.UPDATE))):
    ensure_module("WHATSAPP")
    return service.send_test(db, request)


@router.post("/verify-token")
def rotate_verify_token(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.UPDATE))):
    return service.rotate_verify_token(db)


@router.delete("")
def disconnect(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.UPDATE))):
    return service.disconnect(db)


@webhook_router.get("/webhook/{slug}", include_in_schema=False)
def webhook_verify(slug: str, request: Request, db: Session = Depends(get_db)):
    challenge = service.webhook_verify(db, slug, request.query_params)
    if challenge is None:
        raise NotFound("Not found")
    return PlainTextResponse(challenge)


@webhook_router.post("/webhook/{slug}", include_in_schema=False)
async def webhook_receive(slug: str, request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    result = service.webhook_receive(db, slug, raw, request.headers.get("x-hub-signature-256"))
    if result is None:
        raise NotFound("Not found")
    return result
