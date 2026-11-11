from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.exceptions import PermissionDenied
from ..core.permission import require
from ..db import get_db
from ..permission.dao import PermissionDao
from . import service

router = APIRouter(tags=["Import"], prefix="/api/import")
_NEEDS = {"customers": (Module.CUSTOMER, Action.INSERT), "debts": (Module.PAYMENT, Action.UPDATE)}


@router.get("/template/{kind}", status_code=status.HTTP_200_OK)
def import_template(kind: str, _=Depends(require(Module.IMPORT, Action.SELECT))):
    content, name = service.template(kind)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


@router.post("/{kind}", status_code=status.HTTP_200_OK)
def import_file(kind: str, dryRun: bool = True, file: UploadFile = File(...), db: Session = Depends(get_db),
                current_user=Depends(require(Module.IMPORT, Action.INSERT))):
    module, action = _NEEDS.get(kind, (Module.CUSTOMER, Action.INSERT))
    if not PermissionDao(db).has(current_user.id, module.value, action.value):
        raise PermissionDenied(f"You do not have permission to import {kind}")
    return service.run(db, kind, file.file.read(), dryRun, current_user.id)
