from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.exceptions import PermissionDenied
from ..core.permission import allowed, require, require_any
from ..core.security import TokenData, get_current_user
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Shipment costs"], prefix="/api/shipment")


@router.get("/{package_id}/costs", status_code=status.HTTP_200_OK, response_model=list[schema.Cost])
def list_costs(package_id: str, db: Session = Depends(get_db), _=Depends(require(Module.PROFIT, Action.SELECT))):
    return service.costs(db, package_id)


@router.post("/{package_id}/costs", status_code=status.HTTP_201_CREATED, response_model=schema.Cost)
def add_cost(package_id: str, request: schema.CostCreate, db: Session = Depends(get_db),
             current_user=Depends(require(Module.PROFIT, Action.UPDATE))):
    return service.add_cost(db, package_id, request, current_user.id)


@router.delete("/costs/{cost_id}", status_code=status.HTTP_200_OK)
def delete_cost(cost_id: str, db: Session = Depends(get_db), _=Depends(require(Module.PROFIT, Action.DELETE))):
    return service.delete_cost(db, cost_id)


@router.post("/costs/{cost_id}/pay", status_code=status.HTTP_200_OK, response_model=schema.Cost)
def pay_cost(cost_id: str, request: schema.CostPay, db: Session = Depends(get_db),
             current_user=Depends(require_any((Module.ACCOUNTING, Action.INSERT), (Module.PROFIT, Action.UPDATE)))):
    return service.pay_cost(db, cost_id, request, current_user.id)


@router.get("/costs/{cost_id}/payments", status_code=status.HTTP_200_OK)
def cost_payments(cost_id: str, db: Session = Depends(get_db),
                  _=Depends(require_any((Module.ACCOUNTING, Action.SELECT), (Module.PROFIT, Action.SELECT)))):
    return service.cost_payments(db, cost_id)


@router.get("/costs", status_code=status.HTTP_200_OK)
def all_costs(startDate: str | None = None, endDate: str | None = None, category: str | None = None,
              payStatus: str | None = None, mine: bool = False, box: str | None = None,
              db: Session = Depends(get_db), current_user: TokenData = Depends(get_current_user)):
    """Gharama za mabox: `mine=true` = nilizojaza mimi (kila mtumiaji); zote = Faida/Uhasibu (kuona)."""
    if not mine and not (allowed(db, current_user.id, Module.PROFIT, Action.SELECT)
                         or allowed(db, current_user.id, Module.ACCOUNTING, Action.SELECT)):
        raise PermissionDenied("You do not have permission to view box costs")
    return service.all_costs(db, startDate, endDate, category, payStatus, current_user.id if mine else None, box)


@router.get("/payables", status_code=status.HTTP_200_OK)
def payables(supplier: str | None = None, all: bool = False, db: Session = Depends(get_db),
             _=Depends(require_any((Module.ACCOUNTING, Action.SELECT), (Module.PROFIT, Action.SELECT)))):
    return service.payables(db, supplier, all)


@router.get("/{package_id}/profit", status_code=status.HTTP_200_OK, response_model=schema.Profit)
def box_profit(package_id: str, db: Session = Depends(get_db), _=Depends(require(Module.PROFIT, Action.SELECT))):
    return service.profit(db, package_id)


@router.get("/profit-report", status_code=status.HTTP_200_OK, response_model=schema.ProfitReport)
def profit_report(startDate: str | None = None, endDate: str | None = None, db: Session = Depends(get_db),
                  _=Depends(require(Module.PROFIT, Action.SELECT))):
    return service.profit_report(db, startDate, endDate)
