from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..core.audit import note
from ..core.enums import Action, Module
from ..core.permission import need, require, require_all
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Quotation"], prefix="/api/quotation")


@router.post("/calculate", status_code=status.HTTP_200_OK)
def calculate(request: schema.Calculate, db: Session = Depends(get_db), _=Depends(require(Module.QUOTE, Action.SELECT))):
    """Kuhesabu bei ya bidhaa bila kuhifadhi (ndege = kilo, meli = CBM)."""
    return service.calculate(db, request)


@router.post("", status_code=status.HTTP_201_CREATED)
def create(request: schema.Save, db: Session = Depends(get_db), current_user=Depends(require(Module.QUOTE, Action.INSERT))):
    q = service.create(db, request, current_user.id)
    note(f"Makadirio {q['number']}: {q['customerName']}")
    return q


@router.post("/search", status_code=status.HTTP_200_OK)
def search(request: schema.Search, db: Session = Depends(get_db), current_user=Depends(require(Module.QUOTE, Action.SELECT))):
    return service.search(db, request, current_user.id)


@router.get("/{quotation_id}", status_code=status.HTTP_200_OK)
def get(quotation_id: str, db: Session = Depends(get_db), _=Depends(require(Module.QUOTE, Action.SELECT))):
    return service.get(db, quotation_id)


@router.put("/{quotation_id}", status_code=status.HTTP_200_OK)
def update(quotation_id: str, request: schema.Save, db: Session = Depends(get_db),
           current_user=Depends(require(Module.QUOTE, Action.UPDATE))):
    return service.update(db, quotation_id, request, current_user.id)


@router.put("/{quotation_id}/status", status_code=status.HTTP_200_OK)
def set_status(quotation_id: str, request: schema.SetStatus, db: Session = Depends(get_db),
               _=Depends(require(Module.QUOTE, Action.UPDATE))):
    q = service.set_status(db, quotation_id, request.status)
    note(f"Makadirio {q['number']}: {q['status']}")
    return q


@router.delete("/{quotation_id}", status_code=status.HTTP_200_OK)
def delete(quotation_id: str, db: Session = Depends(get_db), _=Depends(require(Module.QUOTE, Action.DELETE))):
    return service.delete(db, quotation_id)


@router.get("/{quotation_id}/pdf", status_code=status.HTTP_200_OK)
def quotation_pdf(quotation_id: str, db: Session = Depends(get_db), _=Depends(require(Module.QUOTE, Action.SELECT))):
    content, name = service.pdf(db, quotation_id)
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@router.get("/{quotation_id}/message", status_code=status.HTTP_200_OK)
def quotation_message(quotation_id: str, db: Session = Depends(get_db), _=Depends(require(Module.QUOTE, Action.SELECT))):
    """Ujumbe wa SMS wa makadirio (kabla ya kutuma)."""
    q = service._get(db, quotation_id)
    return {"text": service.message(q), "phoneNumber": q.phoneNumber}


@router.post("/{quotation_id}/sms", status_code=status.HTTP_200_OK)
def send_sms(quotation_id: str, request: schema.SendSms, db: Session = Depends(get_db),
             current_user=Depends(require_all((Module.QUOTE, Action.SELECT), (Module.SMS, Action.INSERT)))):
    if (request.channel or "SMS").upper() in ("WHATSAPP", "BOTH"):
        need(db, current_user.id, Module.WHATSAPP, Action.INSERT)
    result = service.send_sms(db, quotation_id, request, current_user.id)
    note(f"Makadirio yametumwa ({result['channel']})")
    return result


@router.post("/{quotation_id}/convert", status_code=status.HTTP_200_OK)
def convert(quotation_id: str, request: schema.Convert, db: Session = Depends(get_db),
            current_user=Depends(require_all((Module.QUOTE, Action.UPDATE), (Module.INVOICE, Action.INSERT),
                                             (Module.PRODUCT, Action.INSERT)))):
    """Makadirio yaliyokubaliwa -> ankara (pamoja na bidhaa zake). Mteja anasajiliwa kama hayupo."""
    result = service.convert(db, quotation_id, request, current_user.id)
    note(f"Makadirio yamegeuzwa kuwa ankara {result['invoiceNumber']}")
    return result
