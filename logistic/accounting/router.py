from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require, require_any
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Accounting"], prefix="/api/accounting")

_VIEW = require(Module.ACCOUNTING, Action.SELECT)
# orodha ya akaunti / makundi kwa fomu (matumizi, malipo) - bila salio
_PICK = require_any((Module.ACCOUNTING, Action.SELECT), (Module.EXPENSES, Action.SELECT),
                    (Module.EXPENSES, Action.INSERT), (Module.PAYMENT, Action.SELECT),
                    (Module.PROFIT, Action.UPDATE))


def _file(content: bytes, name: str, kind: str) -> Response:
    media = "application/pdf" if kind == "pdf" else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(content, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name}.{kind}"'})


# ----------------------------------------------------------- muhtasari (faida na hasara)
@router.get("/summary", status_code=status.HTTP_200_OK)
def summary(startDate: str | None = None, endDate: str | None = None, office: str | None = None,
            db: Session = Depends(get_db), current_user=Depends(_VIEW)):
    return service.summary(db, current_user.id, startDate, endDate, office)


@router.get("/summary.pdf", status_code=status.HTTP_200_OK)
def summary_pdf(startDate: str | None = None, endDate: str | None = None, office: str | None = None,
                db: Session = Depends(get_db), current_user=Depends(_VIEW)):
    content, name = service.summary_pdf(db, current_user.id, startDate, endDate, office)
    return _file(content, name, "pdf")


@router.get("/summary.xlsx", status_code=status.HTTP_200_OK)
def summary_xlsx(startDate: str | None = None, endDate: str | None = None, office: str | None = None,
                 db: Session = Depends(get_db), current_user=Depends(_VIEW)):
    content, name = service.summary_excel(db, current_user.id, startDate, endDate, office)
    return _file(content, name, "xlsx")


# ----------------------------------------------------------- akaunti za fedha
@router.get("/accounts", status_code=status.HTTP_200_OK)
def accounts(office: str | None = None, db: Session = Depends(get_db), current_user=Depends(_VIEW)):
    return service.accounts(db, current_user.id, office)


@router.get("/accounts/options", status_code=status.HTTP_200_OK)
def account_options(db: Session = Depends(get_db), current_user=Depends(_PICK)):
    return service.accounts(db, current_user.id, with_balance=False)["items"]


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(request: schema.AccountSave, db: Session = Depends(get_db),
                   current_user=Depends(require(Module.ACCOUNTING, Action.INSERT))):
    return service.save_account(db, request, current_user.id)


@router.put("/accounts/{id}", status_code=status.HTTP_200_OK)
def update_account(id: str, request: schema.AccountSave, db: Session = Depends(get_db),
                   current_user=Depends(require(Module.ACCOUNTING, Action.UPDATE))):
    return service.save_account(db, request, current_user.id, id)


@router.delete("/accounts/{id}", status_code=status.HTTP_200_OK)
def delete_account(id: str, db: Session = Depends(get_db), _=Depends(require(Module.ACCOUNTING, Action.DELETE))):
    return service.delete_account(db, id)


@router.get("/accounts/{id}/statement", status_code=status.HTTP_200_OK)
def statement(id: str, startDate: str | None = None, endDate: str | None = None, db: Session = Depends(get_db),
              _=Depends(_VIEW)):
    return service.statement(db, id, startDate, endDate)


@router.get("/accounts/{id}/statement.xlsx", status_code=status.HTTP_200_OK)
def statement_xlsx(id: str, startDate: str | None = None, endDate: str | None = None,
                   db: Session = Depends(get_db), _=Depends(_VIEW)):
    content, name = service.statement_excel(db, id, startDate, endDate)
    return _file(content, name, "xlsx")


# ----------------------------------------------------------- makundi
@router.get("/categories", status_code=status.HTTP_200_OK)
def categories(kind: str | None = None, all: bool = False, db: Session = Depends(get_db),
               current_user=Depends(_PICK)):
    return service.categories(db, kind, all, current_user.id)


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(request: schema.CategorySave, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.ACCOUNTING, Action.UPDATE))):
    return service.save_category(db, request, current_user.id)


@router.put("/categories/{id}", status_code=status.HTTP_200_OK)
def update_category(id: str, request: schema.CategorySave, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.ACCOUNTING, Action.UPDATE))):
    return service.save_category(db, request, current_user.id, id)


@router.delete("/categories/{id}", status_code=status.HTTP_200_OK)
def delete_category(id: str, db: Session = Depends(get_db), _=Depends(require(Module.ACCOUNTING, Action.UPDATE))):
    return service.delete_category(db, id)


# ----------------------------------------------------------- mapato mengine
@router.post("/incomes/search", status_code=status.HTTP_200_OK)
def incomes(request: schema.IncomeSearch, db: Session = Depends(get_db), current_user=Depends(_VIEW)):
    return service.incomes(db, request, current_user.id)


@router.post("/incomes", status_code=status.HTTP_201_CREATED)
def create_income(request: schema.IncomeSave, db: Session = Depends(get_db),
                  current_user=Depends(require(Module.ACCOUNTING, Action.INSERT))):
    return service.save_income(db, request, current_user.id)


@router.put("/incomes/{id}", status_code=status.HTTP_200_OK)
def update_income(id: str, request: schema.IncomeSave, db: Session = Depends(get_db),
                  current_user=Depends(require(Module.ACCOUNTING, Action.UPDATE))):
    return service.save_income(db, request, current_user.id, id)


@router.delete("/incomes/{id}", status_code=status.HTTP_200_OK)
def delete_income(id: str, db: Session = Depends(get_db), _=Depends(require(Module.ACCOUNTING, Action.DELETE))):
    return service.delete_income(db, id)


# ----------------------------------------------------------- uhamisho
@router.get("/transfers", status_code=status.HTTP_200_OK)
def transfers(startDate: str | None = None, endDate: str | None = None, account: str | None = None,
              db: Session = Depends(get_db), _=Depends(_VIEW)):
    return service.transfers(db, startDate, endDate, account)


@router.post("/transfers", status_code=status.HTTP_201_CREATED)
def create_transfer(request: schema.TransferSave, db: Session = Depends(get_db),
                    current_user=Depends(require(Module.ACCOUNTING, Action.INSERT))):
    return service.create_transfer(db, request, current_user.id)


@router.delete("/transfers/{id}", status_code=status.HTTP_200_OK)
def delete_transfer(id: str, db: Session = Depends(get_db), _=Depends(require(Module.ACCOUNTING, Action.DELETE))):
    return service.delete_transfer(db, id)


# ----------------------------------------------------------- madeni, mizania, mtaji, kufunga mwezi
@router.get("/payables", status_code=status.HTTP_200_OK)
def payables(db: Session = Depends(get_db),
             _=Depends(require_any((Module.ACCOUNTING, Action.SELECT), (Module.PROFIT, Action.SELECT)))):
    return service.payables(db)


@router.get("/balance-sheet", status_code=status.HTTP_200_OK)
def balance_sheet(db: Session = Depends(get_db), current_user=Depends(_VIEW)):
    return service.balance_sheet(db, current_user.id)


@router.get("/equity", status_code=status.HTTP_200_OK)
def equity(startDate: str | None = None, endDate: str | None = None, db: Session = Depends(get_db), _=Depends(_VIEW)):
    return service.equity(db, startDate, endDate)


@router.post("/equity", status_code=status.HTTP_201_CREATED)
def create_equity(request: schema.EquitySave, db: Session = Depends(get_db),
                  current_user=Depends(require(Module.ACCOUNTING, Action.INSERT))):
    return service.save_equity(db, request, current_user.id)


@router.delete("/equity/{id}", status_code=status.HTTP_200_OK)
def delete_equity(id: str, db: Session = Depends(get_db), _=Depends(require(Module.ACCOUNTING, Action.DELETE))):
    return service.delete_equity(db, id)


@router.get("/locks", status_code=status.HTTP_200_OK)
def locks(db: Session = Depends(get_db), _=Depends(_VIEW)):
    return service.locks(db)


@router.post("/locks", status_code=status.HTTP_201_CREATED)
def lock_month(request: schema.LockSave, db: Session = Depends(get_db),
               current_user=Depends(require(Module.ACCOUNTING, Action.UPDATE))):
    return service.lock_month(db, request, current_user.id)


@router.delete("/locks/{month}", status_code=status.HTTP_200_OK)
def unlock_month(month: str, db: Session = Depends(get_db), _=Depends(require(Module.ACCOUNTING, Action.DELETE))):
    return service.unlock_month(db, month)
