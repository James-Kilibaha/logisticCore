"""
Kikomo cha mkopo cha mteja.

Mkopo = mzigo uliotoka (kukabidhiwa) kabla ya kulipwa. Kiasi kinachotumika = madeni yote ya mteja ambayo
mzigo wake umeshatoka kwa mkopo (ankara DELIVERED, au zilizokabidhiwa kwa awamu kwa mkopo) na bado hayajalipwa.
Kukabidhi kwa mkopo kunakataliwa kama (kinachotumika + deni la ankara hii) kingezidi kikomo.

Kikomo: customer.creditLimit; kisipowekwa (NULL) -> DEFAULT_CREDIT_LIMIT (.env); -1 = hakuna kikomo; 0 = hakuna mkopo.
"""
from sqlalchemy import exists
from sqlalchemy.orm import Session

from .. import config
from ..core.enums import EInvoiceStatus, EPaymentStatus
from ..core.exceptions import BadRequest
from ..core.utils import whole
from ..handover.model import Handover
from ..invoice.model import Invoice
from .model import Debt


def limit_for(customer) -> float | None:
    """Kikomo kinachotumika (TSh), au None = hakuna kikomo."""
    value = customer.creditLimit if customer is not None and customer.creditLimit is not None \
        else config.DEFAULT_CREDIT_LIMIT
    return None if value is None or value < 0 else float(value)


def used(db: Session, customer_id, exclude_invoice=None) -> float:
    """Deni la mizigo iliyokwisha toka kwa mkopo."""
    q = (db.query(Debt.debt).join(Invoice, Invoice.id == Debt.invoice_id)
         .filter(Invoice.customer_id == customer_id, Debt.status != EPaymentStatus.PAID.name, Debt.debt > 0,
                 (Invoice.status == EInvoiceStatus.DELIVERED.name)
                 | exists().where(Handover.invoice_id == Invoice.id, Handover.onCredit.is_(True))))
    if exclude_invoice is not None:
        q = q.filter(Invoice.id != exclude_invoice)
    return float(sum(v or 0 for (v,) in q.all()))


def status(db: Session, customer) -> dict:
    limit = limit_for(customer)
    in_use = used(db, customer.id)
    return {"limit": limit, "own": customer.creditLimit, "default": config.DEFAULT_CREDIT_LIMIT,
            "used": round(in_use, 2), "unlimited": limit is None,
            "available": None if limit is None else round(max(limit - in_use, 0), 2)}


def check(db: Session, customer, invoice, balance: float) -> None:
    """Inakataa kukabidhi kwa mkopo kama kikomo kingezidi."""
    limit = limit_for(customer)
    if limit is None or customer is None:
        return
    in_use = used(db, customer.id, exclude_invoice=invoice.id)
    if in_use + balance > limit + 0.5:
        available = max(limit - in_use, 0)
        if limit <= 0:
            raise BadRequest(f"Mteja {customer.name} hakopeshwi (kikomo cha mkopo ni 0). Pokea malipo kwanza "
                             f"/ this customer has no credit allowance")
        raise BadRequest(f"Kikomo cha mkopo kimezidi: kikomo TSh {whole(limit)}, deni la mkopo sasa TSh {whole(in_use)}, "
                         f"kinachopatikana TSh {whole(available)}, ankara hii TSh {whole(balance)}. "
                         f"Pokea malipo au ongeza kikomo / credit limit exceeded")
