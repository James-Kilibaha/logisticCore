from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Payment"], prefix="/api/payment")


def _pdf(content: bytes, name: str) -> Response:
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@router.post("", status_code=status.HTTP_200_OK)
def create_payment(request: schema.CreatePayment, db: Session = Depends(get_db),
                   current_user=Depends(require(Module.PAYMENT, Action.INSERT))):
    return service.create_payment(db, request, current_user.id)


@router.post("/search-payment", status_code=status.HTTP_200_OK)
def search_payment(request: schema.SearchPayment, db: Session = Depends(get_db),
                   _=Depends(require(Module.PAYMENT, Action.SELECT))):
    return service.search(db, request)


@router.put("/discount", status_code=status.HTTP_200_OK)
def set_discount(request: schema.Discount, db: Session = Depends(get_db),
                 current_user=Depends(require(Module.DISCOUNT, Action.INSERT))):
    return service.set_discount(db, request, current_user.id)


@router.post("/refund", status_code=status.HTTP_200_OK)
def refund(request: schema.Refund, db: Session = Depends(get_db),
           current_user=Depends(require(Module.REFUND, Action.INSERT))):
    return service.refund(db, request, current_user.id)


@router.get("/{payment_id}/receipt", status_code=status.HTTP_200_OK)
def receipt(payment_id: str, db: Session = Depends(get_db), _=Depends(require(Module.PAYMENT, Action.SELECT))):
    content, name = service.receipt_pdf(db, payment_id)
    return _pdf(content, name)
