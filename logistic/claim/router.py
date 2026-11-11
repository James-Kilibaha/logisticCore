from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Claims"], prefix="/api/claim")


@router.post("", status_code=status.HTTP_201_CREATED, response_model=schema.Display)
def create_claim(stringValue: str = Form(...), photo: UploadFile | None = File(None), db: Session = Depends(get_db),
                 current_user=Depends(require(Module.CLAIM, Action.INSERT))):
    data = service.parse(stringValue)
    upload = (photo.filename or "photo.jpg", photo.file.read()) if photo is not None else None
    return service.create(db, data, upload, current_user.id)


@router.post("/search", status_code=status.HTTP_200_OK, response_model=list[schema.Display])
def search_claims(request: schema.Filter, db: Session = Depends(get_db),
                  _=Depends(require(Module.CLAIM, Action.SELECT))):
    return service.search(db, request)


@router.get("/counts", status_code=status.HTTP_200_OK)
def claim_counts(db: Session = Depends(get_db), _=Depends(require(Module.CLAIM, Action.SELECT))):
    return service.counts(db)


@router.put("/{claim_id}/resolve", status_code=status.HTTP_200_OK, response_model=schema.Display)
def resolve_claim(claim_id: str, request: schema.Resolve, db: Session = Depends(get_db),
                  current_user=Depends(require(Module.CLAIM, Action.UPDATE))):
    return service.resolve(db, claim_id, request, current_user.id)


@router.get("/{claim_id}/photo", status_code=status.HTTP_200_OK)
def claim_photo(claim_id: str, db: Session = Depends(get_db), _=Depends(require(Module.CLAIM, Action.SELECT))):
    return FileResponse(service.photo_path(db, claim_id))
