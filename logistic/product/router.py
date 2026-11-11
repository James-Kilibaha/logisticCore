from fastapi import APIRouter, Request, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require, require_any
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Product"], prefix="/api/product")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_product(stringValue: str = Form(...), file: UploadFile | None = File(None), db: Session = Depends(get_db),
                   current_user=Depends(require(Module.PRODUCT, Action.INSERT))):
    data = service.parse_create(stringValue)
    if file is None:
        return service.create(db, data, None, None, current_user.id)
    return service.create(db, data, file.filename, file.file.read(), current_user.id)


@router.get("/open-images/{folder}/{imagesFolder}/{image}", status_code=status.HTTP_200_OK)
def open_image(folder: str, imagesFolder: str, image: str, http: Request, t: str | None = None,
               db: Session = Depends(get_db)):
    """
    Picha ya mzigo - kwa aliyeingia tu. Token inatumwa kwenye header au `?t=` (picha za web haziwezi kutuma header).
    """
    from ..core.exceptions import PermissionDenied
    from ..core.security import get_current_user
    from ..permission.dao import PermissionDao

    header = http.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else (t or "")
    user = get_current_user(token)  # 401 kama token si halali
    dao = PermissionDao(db)
    if not any(dao.has(user.id, m.value, Action.SELECT.value)
               for m in (Module.PRODUCT, Module.INVOICE, Module.STORE, Module.PACKAGE)):
        raise PermissionDenied("You do not have permission to view products")
    return FileResponse(service.image_path(folder, imagesFolder, image))


def _token_user(http: Request, t: str | None):
    from ..core.security import get_current_user

    header = http.headers.get("authorization", "")
    return get_current_user(header[7:] if header.lower().startswith("bearer ") else (t or ""))


@router.post("/photo/{code}", status_code=status.HTTP_200_OK)
async def upload_photo_by_code(code: str, file: UploadFile = File(...), db: Session = Depends(get_db),
                               _=Depends(require_any((Module.PRODUCT, Action.UPDATE), (Module.PRODUCT, Action.INSERT)))):
    """Picha ya mzigo kutoka simu (QR ya code ya ofisi): inawekwa kwenye mzigo, au inasubiri usajili."""
    from . import photo

    return photo.upload(db, code, file.filename, await file.read())


@router.get("/photo/{code}/status", status_code=status.HTTP_200_OK)
def photo_status(code: str, db: Session = Depends(get_db), _=Depends(require(Module.PRODUCT, Action.SELECT))):
    from . import photo

    return photo.status(db, code)


@router.delete("/photo/{code}/staged", status_code=status.HTTP_200_OK)
def photo_discard(code: str, _=Depends(require_any((Module.PRODUCT, Action.UPDATE), (Module.PRODUCT, Action.INSERT)))):
    from . import photo

    return photo.discard_staged(code)


@router.get("/photo/{code}/staged", status_code=status.HTTP_200_OK)
def photo_staged(code: str, http: Request, t: str | None = None, db: Session = Depends(get_db)):
    """Picha inayosubiri (kwa web kuonyesha kwenye fomu). Token kwenye header au `?t=`."""
    from ..core.exceptions import PermissionDenied
    from ..permission.dao import PermissionDao
    from . import photo

    user = _token_user(http, t)
    if not PermissionDao(db).has(user.id, Module.PRODUCT.value, Action.SELECT.value):
        raise PermissionDenied("You do not have permission to view products")
    return FileResponse(photo.staged_file(code))


@router.put("", status_code=status.HTTP_201_CREATED)
def update_product(request: schema.Update, db: Session = Depends(get_db),
                   _=Depends(require(Module.PRODUCT, Action.UPDATE))):
    return service.update(db, request)


@router.get("", status_code=status.HTTP_200_OK)
def get_all_products(db: Session = Depends(get_db), _=Depends(require(Module.PRODUCT, Action.SELECT))):
    return service.list_all(db)


@router.get("/{invoice_id}", status_code=status.HTTP_200_OK)
def get_products_by_invoice(invoice_id: str, db: Session = Depends(get_db),
                            _=Depends(require(Module.PRODUCT, Action.SELECT))):
    return service.by_invoice(db, invoice_id)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
def delete_product(id: str, db: Session = Depends(get_db), _=Depends(require(Module.PRODUCT, Action.DELETE))):
    return service.delete(db, id)
