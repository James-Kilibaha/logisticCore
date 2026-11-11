from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config
from ..core.enums import Action, Module
from ..core.permission import require
from ..core.security import TokenData
from ..db import get_db
from ..core.audit import note
from ..core.scope import office_scope
from . import broadcast, schema, service
from .invoice_sms import InvoiceSms as InvoiceSmsBody

router = APIRouter(tags=["Sms"], prefix="/api/sms")


@router.post("", status_code=status.HTTP_200_OK)
def search_sms(request: schema.Search, db: Session = Depends(get_db), _=Depends(require(Module.SMS, Action.SELECT))):
    return service.search(db, request)


class CreditBody(BaseModel):
    kind: str = "ADD"   # ADD = SMS zilizonunuliwa, SET = salio halisi la sasa (kutoka FastHub)
    amount: int
    note: str | None = None


@router.get("/balance", status_code=status.HTTP_200_OK)
def sms_balance(db: Session = Depends(get_db), _=Depends(require(Module.SMS, Action.SELECT))):
    """Salio la SMS (kutoka FastHub kama SMS_BALANCE_API imewekwa, la sivyo makadirio) na matumizi ya mwezi."""
    from . import credit

    return credit.status(db)


@router.post("/balance", status_code=status.HTTP_200_OK)
def sms_balance_record(request: CreditBody, db: Session = Depends(get_db),
                       current_user=Depends(require(Module.SETTING, Action.UPDATE))):
    """Kurekodi SMS zilizonunuliwa (ADD) au salio halisi la sasa (SET)."""
    from . import credit

    credit.record(db, request.kind, request.amount, request.note, current_user.id)
    note(f"Salio la SMS: {request.kind} {request.amount}")
    return credit.status(db, ask_gateway=False)


@router.get("/delivery-summary", status_code=status.HTTP_200_OK)
def delivery_summary(days: int = 30, db: Session = Depends(get_db), _=Depends(require(Module.SMS, Action.SELECT))):
    """Ujumbe uliotumwa siku `days` zilizopita kwa hali ya kufika (SENT / DELIVERED / FAILED / UNKNOWN)."""
    from datetime import timedelta

    from ..core.base_model import utc_now
    from . import dlr

    return {"days": days, "dlrEnabled": bool(config.SMS_DLR_TOKEN), "byChannel": dlr.summary(db, utc_now() - timedelta(days=max(1, min(days, 365))))}


@router.post("/resend", status_code=status.HTTP_200_OK)
def resend_sms(request: schema.Resend, db: Session = Depends(get_db),
               current_user: TokenData = Depends(require(Module.SMS, Action.INSERT))):
    """Kutuma tena ujumbe (nakala mpya); wa awali unabaki kwenye historia."""
    return service.resend(db, request, current_user.id)


@router.post("/send", status_code=status.HTTP_200_OK)
def send_sms(request: schema.SendFrom, db: Session = Depends(get_db), _=Depends(require(Module.SMS, Action.INSERT))):
    return service.send(db, request)


def _need(db: Session, user_id, module: Module, action: Action, what: str) -> None:
    from ..core.exceptions import PermissionDenied
    from ..permission.dao import PermissionDao

    if not PermissionDao(db).has(user_id, module.value, action.value):
        raise PermissionDenied(f"Huna ruhusa ya {what} / you do not have permission")
    from ..saas.subscription.service import ensure_module

    ensure_module(module.value)


def _many_allowed(db: Session, request, user_id) -> None:
    """Mteja mmoja = SMS; wengi / wote / makundi = ruhusa ya BROADCAST."""
    if (request.audience or "ALL").upper() != "ONE":
        _need(db, user_id, Module.BROADCAST, Action.INSERT, "kutuma ujumbe kwa wateja wengi")


@router.post("/broadcast/preview", status_code=status.HTTP_200_OK)
def broadcast_preview(request: broadcast.Broadcast, db: Session = Depends(get_db),
                      current_user=Depends(require(Module.SMS, Action.INSERT))):
    """Walengwa wangapi, SMS ngapi na mfano wa ujumbe (kabla ya kutuma)."""
    _many_allowed(db, request, current_user.id)
    return broadcast.preview(db, request, office_scope(db, current_user.id))


@router.post("/broadcast", status_code=status.HTTP_200_OK)
def broadcast_send(request: broadcast.Broadcast, db: Session = Depends(get_db),
                   current_user=Depends(require(Module.SMS, Action.INSERT))):
    """Ujumbe kwa mteja mmoja, waliochaguliwa au wote (SMS / WhatsApp / zote)."""
    _many_allowed(db, request, current_user.id)
    if (request.channel or "SMS").upper() in ("WHATSAPP", "BOTH"):
        _need(db, current_user.id, Module.WHATSAPP, Action.INSERT, "kutuma WhatsApp")
    result = broadcast.send(db, request, current_user.id, office_scope(db, current_user.id))
    note(f"Ujumbe kwa wateja {result['recipients']} ({result['channel']}): {request.text[:80]}")
    return result


@router.get("/invoice/{invoice_id}/preview", status_code=status.HTTP_200_OK)
def invoice_sms_preview(invoice_id: str, db: Session = Depends(get_db),
                        current_user=Depends(require(Module.SMS, Action.INSERT))):
    """Ujumbe wa ankara (bidhaa moja moja, jumla, deni) kabla ya kutuma."""
    from . import invoice_sms

    _need(db, current_user.id, Module.INVOICE, Action.SELECT, "kuona ankara")
    return invoice_sms.preview(db, invoice_id)


@router.post("/invoice", status_code=status.HTTP_200_OK)
def invoice_sms_send(request: InvoiceSmsBody, db: Session = Depends(get_db),
                     current_user=Depends(require(Module.SMS, Action.INSERT))):
    """Kutuma SMS ya ankara kwa mteja na/au mpokeaji."""
    from . import invoice_sms

    _need(db, current_user.id, Module.INVOICE, Action.SELECT, "kuona ankara")
    if (request.channel or "SMS").upper() in ("WHATSAPP", "BOTH"):
        _need(db, current_user.id, Module.WHATSAPP, Action.INSERT, "kutuma WhatsApp")
    result = invoice_sms.send(db, request, current_user.id)
    note(f"SMS ya ankara kwa watu {result['recipients']} ({result['channel']})")
    return result


class AutoRule(BaseModel):
    kind: str
    enabled: bool | None = None
    afterDays: int | None = None
    everyDays: int | None = None
    autoSend: bool | None = None
    hour: int | None = None


@router.get("/auto-rules", status_code=status.HTTP_200_OK)
def auto_rules(db: Session = Depends(get_db), _=Depends(require(Module.SETTING, Action.SELECT))):
    """SMS za moja kwa moja: deni, mkopo, onyo la stoo, mzigo umekaa stoo muda mrefu."""
    from . import reminders

    return reminders.rules(db)


@router.put("/auto-rules", status_code=status.HTTP_200_OK)
def update_auto_rules(request: list[AutoRule], db: Session = Depends(get_db),
                      _=Depends(require(Module.SETTING, Action.UPDATE))):
    from . import reminders

    return reminders.update_rules(db, [r.model_dump() for r in request])


@router.post("/reminders/run", status_code=status.HTTP_200_OK)
def run_reminders(db: Session = Depends(get_db), current_user=Depends(require(Module.BROADCAST, Action.INSERT))):
    """Kuendesha SMS za moja kwa moja zilizowashwa sasa hivi (kawaida zinajiendesha kila siku saa iliyowekwa)."""
    from . import reminders

    return reminders.run(db, current_user.id)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
def delete_sms(id: str, db: Session = Depends(get_db), _=Depends(require(Module.SMS, Action.DELETE))):
    return service.delete(db, id)
