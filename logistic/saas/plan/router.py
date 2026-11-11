from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ...db import get_db
from ..admin.service import current_admin
from . import schema, service

router = APIRouter(tags=["Platform - Plans"], prefix="/api/platform/plans", dependencies=[Depends(current_admin)])


@router.get("", response_model=list[schema.PlanOut])
def list_plans(db: Session = Depends(get_db)):
    return service.list_all(db)


@router.get("/modules")
def optional_modules():
    """Moduli za ziada zinazoweza kuwekwa kwenye mpango."""
    return service.OPTIONAL_MODULES


@router.post("", response_model=schema.PlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(request: schema.PlanCreate, db: Session = Depends(get_db)):
    return service.create(db, request)


@router.put("", response_model=schema.PlanOut)
def update_plan(request: schema.PlanUpdate, db: Session = Depends(get_db)):
    return service.update(db, request)


@router.delete("/{plan_id}")
def delete_plan(plan_id: str, db: Session = Depends(get_db)):
    return service.delete(db, plan_id)
