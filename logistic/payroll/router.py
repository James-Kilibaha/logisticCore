from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Payroll"], prefix="/api/payroll")

_VIEW = require(Module.PAYROLL, Action.SELECT)


def _file(content: bytes, name: str, kind: str) -> Response:
    media = "application/pdf" if kind == "pdf" else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{kind}"'})


@router.get("/settings", status_code=status.HTTP_200_OK)
def get_settings(db: Session = Depends(get_db), _=Depends(_VIEW)):
    return service.settings_dict(db)


@router.put("/settings", status_code=status.HTTP_200_OK)
def save_settings(request: schema.SettingsSave, db: Session = Depends(get_db),
                  _=Depends(require(Module.PAYROLL, Action.UPDATE))):
    return service.save_settings(db, request)


@router.get("/employees", status_code=status.HTTP_200_OK)
def employees(all: bool = False, db: Session = Depends(get_db), _=Depends(_VIEW)):
    return service.employees(db, all)


@router.post("/employees", status_code=status.HTTP_201_CREATED)
def create_employee(request: schema.EmployeeSave, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.PAYROLL, Action.INSERT))):
    return service.save_employee(db, request, current_user.id)


@router.put("/employees/{id}", status_code=status.HTTP_200_OK)
def update_employee(id: str, request: schema.EmployeeSave, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.PAYROLL, Action.UPDATE))):
    return service.save_employee(db, request, current_user.id, id)


@router.delete("/employees/{id}", status_code=status.HTTP_200_OK)
def delete_employee(id: str, db: Session = Depends(get_db), _=Depends(require(Module.PAYROLL, Action.DELETE))):
    return service.delete_employee(db, id)


@router.get("/runs", status_code=status.HTTP_200_OK)
def runs(db: Session = Depends(get_db), _=Depends(_VIEW)):
    return service.runs(db)


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def prepare(request: schema.Prepare, db: Session = Depends(get_db),
            current_user=Depends(require(Module.PAYROLL, Action.INSERT))):
    return service.prepare(db, request.month, current_user.id)


@router.get("/runs/{id}", status_code=status.HTTP_200_OK)
def get_run(id: str, db: Session = Depends(get_db), _=Depends(_VIEW)):
    return service.get_run(db, id)


@router.put("/runs/{id}/lines/{line_id}", status_code=status.HTTP_200_OK)
def edit_line(id: str, line_id: str, request: schema.LineEdit, db: Session = Depends(get_db),
              _=Depends(require(Module.PAYROLL, Action.UPDATE))):
    return service.edit_line(db, id, line_id, request)


@router.post("/runs/{id}/post", status_code=status.HTTP_200_OK)
def post_run(id: str, request: schema.Post, db: Session = Depends(get_db),
             current_user=Depends(require(Module.PAYROLL, Action.UPDATE))):
    return service.post(db, id, request.institute_id, current_user.id)


@router.delete("/runs/{id}", status_code=status.HTTP_200_OK)
def delete_run(id: str, db: Session = Depends(get_db), _=Depends(require(Module.PAYROLL, Action.DELETE))):
    return service.delete_run(db, id)


@router.get("/runs/{id}/sheet.pdf", status_code=status.HTTP_200_OK)
def sheet_pdf(id: str, db: Session = Depends(get_db), _=Depends(_VIEW)):
    content, name = service.sheet_pdf(db, id)
    return _file(content, name, "pdf")


@router.get("/runs/{id}/sheet.xlsx", status_code=status.HTTP_200_OK)
def sheet_xlsx(id: str, db: Session = Depends(get_db), _=Depends(_VIEW)):
    content, name = service.sheet_excel(db, id)
    return _file(content, name, "xlsx")
