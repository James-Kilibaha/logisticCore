from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import schema, search, service

router = APIRouter(tags=["Handover"], prefix="/api/handover")


@router.post("/search", status_code=status.HTTP_200_OK)
def search_handovers(request: search.Filter, db: Session = Depends(get_db),
                     current_user=Depends(require(Module.HANDOVER, Action.SELECT))):
    """Mizigo iliyokabidhiwa: tarehe, mteja, aliyekabidhi, mchukuaji, jina la mzigo/track, usafiri (AIR/SEA)."""
    from ..core.scope import office_scope

    return search.search(db, request, office_scope(db, current_user.id))


@router.post("/export", status_code=status.HTTP_200_OK)
def export_handovers(request: search.Filter, db: Session = Depends(get_db),
                     current_user=Depends(require(Module.HANDOVER, Action.SELECT))):
    """Excel ya mizigo iliyokabidhiwa (vichujio vile vile vya /search)."""
    from ..core.scope import office_scope

    content, name = search.export(db, request, office_scope(db, current_user.id))
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


def _read(upload: UploadFile | None):
    return (upload.filename or "image.png", upload.file.read()) if upload is not None else None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=schema.Display)
def create_handover(stringValue: str = Form(...), signature: UploadFile | None = File(None),
                    photo: UploadFile | None = File(None), db: Session = Depends(get_db),
                    current_user=Depends(require(Module.HANDOVER, Action.INSERT))):
    data = service.parse(stringValue)
    return service.create(db, data, _read(signature), _read(photo), current_user.id)


@router.get("/{invoiceId}", status_code=status.HTTP_200_OK, response_model=schema.Display)
def get_handover(invoiceId: str, db: Session = Depends(get_db), _=Depends(require(Module.HANDOVER, Action.SELECT))):
    return service.by_invoice(db, invoiceId)


@router.get("/{invoiceId}/status", status_code=status.HTTP_200_OK, response_model=schema.Status)
def handover_status(invoiceId: str, db: Session = Depends(get_db), _=Depends(require(Module.HANDOVER, Action.SELECT))):
    """Makabidhiano yote ya ankara + katoni zilizobaki kwa kila bidhaa."""
    return service.status(db, invoiceId)


@router.get("/{invoiceId}/pdf", status_code=status.HTTP_200_OK)
def handover_pdf(invoiceId: str, handoverId: str | None = None, db: Session = Depends(get_db),
                 _=Depends(require(Module.HANDOVER, Action.SELECT))):
    content, name = service.note_pdf(db, invoiceId, handoverId)
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@router.get("/{invoiceId}/file/{kind}", status_code=status.HTTP_200_OK)
def handover_file(invoiceId: str, kind: str, handoverId: str | None = None, db: Session = Depends(get_db),
                  _=Depends(require(Module.HANDOVER, Action.SELECT))):
    return FileResponse(service.file_path(db, invoiceId, kind, handoverId))
