"""Kutuma PDF (ankara, risiti, hati ya makabidhiano) kwa mteja kupitia WhatsApp."""
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config
from ..core import whatsapp
from ..core.audit import note
from ..core.enums import Action, Module
from ..core.exceptions import BadRequest, NotFound
from ..core.permission import require
from ..db import get_db

router = APIRouter(tags=["WhatsApp"], prefix="/api/whatsapp")


class SendDocument(BaseModel):
    invoiceId: UUID
    kind: str = "INVOICE"          # INVOICE / RECEIPT / HANDOVER
    paymentId: UUID | None = None  # kwa RECEIPT
    phone: str | None = None       # tupu = simu ya mteja


@router.get("/status", status_code=status.HTTP_200_OK)
def whatsapp_status(_=Depends(require(Module.WHATSAPP, Action.SELECT))):
    return {"configured": whatsapp.configured(), "enabled": config.WHATSAPP_ENABLED,
            "template": bool(config.WHATSAPP_TEMPLATE), "documentTemplate": bool(config.WHATSAPP_DOC_TEMPLATE),
            "imageTemplate": bool(config.WHATSAPP_IMAGE_TEMPLATE)}


@router.post("/document", status_code=status.HTTP_200_OK)
def send_document(request: SendDocument, db: Session = Depends(get_db),
                  current_user=Depends(require(Module.WHATSAPP, Action.INSERT))):
    from ..invoice.dao import InvoiceDao
    from ..sms.dao import SmsDao

    invoice = InvoiceDao(db).with_details(request.invoiceId)
    if invoice is None:
        raise NotFound("The Invoice does not exist")
    customer = invoice.customer[0] if invoice.customer else None
    phone = _phone(request.phone, customer)
    kind = request.kind.upper()
    name = customer.name if customer else ""

    if kind == "INVOICE":
        from ..invoice import schema as invoice_schema
        from ..invoice import service as invoice_service

        path = invoice_service.generate_pdf(db, invoice_schema.InvoiceStatusRef(id=str(invoice.id)))
        content, filename = path.read_bytes(), f"ankara_{invoice.invoiceNumber}.pdf"
        caption = f"Habari {name}, hii ni ankara yako No. {invoice.invoiceNumber} kutoka {config.COMPANY_NAME}."
    elif kind == "RECEIPT":
        from ..payment import service as payment_service

        if request.paymentId is None:
            raise BadRequest("paymentId is required for a receipt")
        content, base = payment_service.receipt_pdf(db, request.paymentId)
        filename = f"{base}.pdf"
        caption = f"Habari {name}, hii ni risiti ya malipo yako (ankara {invoice.invoiceNumber}). Ahsante."
    elif kind == "HANDOVER":
        from ..handover import service as handover_service

        content, base = handover_service.note_pdf(db, invoice.id)
        filename = f"{base}.pdf"
        caption = f"Habari {name}, hii ni hati ya makabidhiano ya mzigo wa ankara {invoice.invoiceNumber}."
    else:
        raise BadRequest("kind must be INVOICE, RECEIPT or HANDOVER")

    message_id = whatsapp.send_document(phone, content, filename, caption)
    SmsDao(db).create(text=f"[PDF] {filename} - {caption}", msisdn=phone, source="WhatsApp",
                      reference=invoice.invoiceNumber, coding="UTF8", smsFor="WHATSAPP", isReceived=False,
                      isSMSSend=True, channel="WHATSAPP", invoice_id=invoice.id, logsId=current_user.id)
    note(f"WhatsApp: {filename} imetumwa kwa {phone}")
    return {"sent": True, "messageId": message_id, "to": whatsapp.to_international(phone)}



def _phone(given: str | None, customer) -> str:
    """Namba ya kutuma: iliyoandikwa (lazima +255XXXXXXXXX) au ya mteja."""
    from ..core.phone import normalize, try_normalize

    if given and given.strip():
        return normalize(given)
    phone = try_normalize(customer.phoneNumber if customer else None)
    if not phone:
        raise BadRequest("Mteja hana namba sahihi ya simu (+255XXXXXXXXX) / customer has no valid phone number")
    return phone


def _log(db: Session, phone: str, text: str, invoice, user_id) -> None:
    from ..sms.dao import SmsDao

    SmsDao(db).create(text=text[:1000], msisdn=phone, source="WhatsApp",
                      reference=invoice.invoiceNumber if invoice else "manual", coding="UTF8", smsFor="WHATSAPP",
                      isReceived=False, isSMSSend=True, channel="WHATSAPP",
                      invoice_id=invoice.id if invoice else None, logsId=user_id)


@router.post("/message", status_code=status.HTTP_200_OK)
def send_message(text: str = Form(..., min_length=1), invoiceId: str | None = Form(None),
                 phone: str | None = Form(None), image: UploadFile | None = File(None),
                 db: Session = Depends(get_db), current_user=Depends(require(Module.WHATSAPP, Action.INSERT))):
    """Ujumbe wa WhatsApp (pamoja na picha, si lazima) kwa mteja wa ankara au kwa namba yoyote."""
    from ..invoice.dao import InvoiceDao

    invoice = InvoiceDao(db).with_details(invoiceId) if invoiceId else None
    if invoiceId and invoice is None:
        raise NotFound("The Invoice does not exist")
    customer = invoice.customer[0] if invoice and invoice.customer else None
    to = _phone(phone, customer)
    if image is not None:
        message_id = whatsapp.send_image(to, image.file.read(), image.filename or "picha.jpg", text)
        _log(db, to, f"[PICHA] {text}", invoice, current_user.id)
    else:
        message_id = whatsapp.send_text(to, text)
        _log(db, to, text, invoice, current_user.id)
    note(f"WhatsApp kwa {to}" + (" (pamoja na picha)" if image is not None else ""))
    return {"sent": True, "messageId": message_id, "to": whatsapp.to_international(to)}


class SendPhotos(BaseModel):
    invoiceId: UUID
    phone: str | None = None


@router.post("/product-photos", status_code=status.HTTP_200_OK)
def send_product_photos(request: SendPhotos, db: Session = Depends(get_db),
                        current_user=Depends(require(Module.WHATSAPP, Action.INSERT))):
    """Picha za mizigo ya ankara (zilizopigwa wakati wa kupokea) kwa mteja - picha moja kwa kila mzigo."""
    from ..core import files
    from ..invoice.dao import InvoiceDao

    invoice = InvoiceDao(db).with_details(request.invoiceId)
    if invoice is None:
        raise NotFound("The Invoice does not exist")
    customer = invoice.customer[0] if invoice.customer else None
    to = _phone(request.phone, customer)
    sent, missing = 0, 0
    for p in invoice.product:
        if not p.path:
            missing += 1
            continue
        try:
            path = files.existing(p.path)
        except NotFound:
            missing += 1
            continue
        caption = (f"Mzigo wako: {p.description} · katoni {p.quantities:g} · kilo {p.weight:g}"
                   f"{' · Track ' + p.trackNumber if p.trackNumber else ''} (ankara {invoice.invoiceNumber})")
        whatsapp.send_image(to, path.read_bytes(), path.name, caption)
        _log(db, to, f"[PICHA] {caption}", invoice, current_user.id)
        sent += 1
    if sent == 0:
        raise BadRequest("This invoice has no cargo photos")
    note(f"WhatsApp: picha {sent} za mizigo ya ankara {invoice.invoiceNumber} kwa {to}")
    return {"sent": sent, "withoutPhoto": missing, "to": whatsapp.to_international(to)}


# ------------------------------------------------------------------ inbox (majibu ya wateja)

class Reply(BaseModel):
    phone: str
    text: str


class PhoneRef(BaseModel):
    phone: str


@router.get("/inbox", status_code=status.HTTP_200_OK)
def inbox_conversations(q: str | None = Query(None), db: Session = Depends(get_db),
                        _=Depends(require(Module.WHATSAPP, Action.SELECT))):
    """Mazungumzo (namba kwa namba), mapya kwanza, pamoja na idadi ya ambayo hayajasomwa."""
    from . import inbox

    return inbox.conversations(db, q)


@router.get("/inbox/unread", status_code=status.HTTP_200_OK)
def inbox_unread(db: Session = Depends(get_db), _=Depends(require(Module.WHATSAPP, Action.SELECT))):
    from . import inbox

    return inbox.unread(db)


@router.get("/inbox/thread", status_code=status.HTTP_200_OK)
def inbox_thread(phone: str = Query(...), db: Session = Depends(get_db),
                 current_user=Depends(require(Module.WHATSAPP, Action.SELECT))):
    """Ujumbe wote wa namba moja (inaweka 'imesomwa' - isipokuwa super admin anayeangalia tu)."""
    from . import inbox

    return inbox.thread(db, phone, mark_read=not getattr(current_user, "imp", None))


@router.post("/inbox/reply", status_code=status.HTTP_200_OK)
def inbox_reply(request: Reply, db: Session = Depends(get_db),
                current_user=Depends(require(Module.WHATSAPP, Action.INSERT))):
    from . import inbox

    out = inbox.reply(db, request.phone, request.text, user_id=current_user.id)
    note(f"WhatsApp: jibu kwa {request.phone}")
    return out


@router.post("/inbox/read", status_code=status.HTTP_200_OK)
def inbox_read(request: PhoneRef, db: Session = Depends(get_db),
               _=Depends(require(Module.WHATSAPP, Action.SELECT))):
    from . import inbox

    return inbox.mark_read(db, request.phone)


@router.get("/inbox/media/{message_id}")
def inbox_media(message_id: str, db: Session = Depends(get_db), _=Depends(require(Module.WHATSAPP, Action.SELECT))):
    """Picha / PDF / sauti iliyotumwa na mteja (inaletwa kutoka Meta)."""
    from . import inbox

    content, mime, name = inbox.media(db, message_id)
    return Response(content, media_type=mime, headers={"Content-Disposition": f'inline; filename="{name}"'})
