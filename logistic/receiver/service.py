from sqlalchemy.orm import Session

from ..core.exceptions import BadRequest, Conflict, NotFound
from ..core import phone as phones
from ..core.utils import stamp
from ..invoice.dao import InvoiceDao
from . import schema
from .dao import ReceiverDao
from .model import Receiver


def create(db: Session, data: schema.Insert, current_user_id) -> Receiver:
    """Kusajili mpokeaji wa invoice na kubadilisha hali ya invoice kwa wakati mmoja."""
    dao = ReceiverDao(db)
    track = data.trackNumber.strip()
    if dao.by_track_number(track):
        raise Conflict("This Track Number already exists...")

    existing = dao.by_invoice(data.invoice_id)
    if existing:
        number = existing.invoice[0].invoiceNumber if existing.invoice else ""
        raise Conflict(f"Receiver already exists for this Invoice {number}")

    invoice_dao = InvoiceDao(db)
    invoice = invoice_dao.get(data.invoice_id)
    if invoice is None:
        raise NotFound("Invoice not Existed...")

    invoice_dao.change_status(invoice, data.status, data.history or stamp(data.status), commit=False)
    return dao.create(name=data.name.strip(), phoneNumber=phones.normalize(data.phoneNumber), trackNumber=track,
                      active=data.active, invoice_id=invoice.id, logsId=current_user_id)


def list_all(db: Session):
    return ReceiverDao(db).all()


def list_not_blocked(db: Session):
    return ReceiverDao(db).not_blocked()


def toggle_block(db: Session, data: schema.Block) -> Receiver:
    dao = ReceiverDao(db)
    receiver = dao.get(data.id) if data.id else dao.by_phone(phones.try_normalize(data.phoneNumber))
    if receiver is None:
        raise NotFound("The Receiver does not exist")
    return dao.update(receiver, active=0 if receiver.active == 1 else 1)


_DONE = ("DELIVERED", "COMPLETED")


def _invoice_of(receiver):
    return receiver.invoice[0] if receiver.invoice else None


def update(db: Session, data: schema.Update) -> Receiver:
    """Kurekebisha jina / simu / namba ya kuchukulia ya mpokeaji (kabla mzigo haujakabidhiwa)."""
    dao = ReceiverDao(db)
    receiver = dao.get(data.id)
    if receiver is None:
        raise NotFound("Mpokeaji hayupo")
    invoice = _invoice_of(receiver)
    if invoice is not None and (invoice.status or "").upper() in _DONE:
        raise BadRequest("Mzigo umeshakabidhiwa; taarifa za mpokeaji haziwezi kubadilishwa")
    track = data.trackNumber.strip()
    other = dao.by_track_number(track)
    if other is not None and other.id != receiver.id:
        raise Conflict("Namba hii ya kuchukulia inatumika kwa mpokeaji mwingine")
    return dao.update(receiver, name=data.name.strip(), phoneNumber=phones.normalize(data.phoneNumber),
                      trackNumber=track)


def delete(db: Session, receiver_id) -> bool:
    """
    Kufuta mpokeaji aliyesajiliwa kimakosa. Ankara iliyokuwa tayari kupakiwa (PARKING) inarudi kuwa wazi (OPEN)
    ili mpokeaji sahihi asajiliwe. Mzigo ukishasafirishwa, hariri mpokeaji badala ya kumfuta.
    """
    dao = ReceiverDao(db)
    receiver = dao.get(receiver_id)
    if receiver is None:
        raise NotFound("The Receiver does not exist")
    invoice = _invoice_of(receiver)
    status = (invoice.status or "").upper() if invoice is not None else ""
    if invoice is not None and status not in ("OPEN", "PARKING", "BLOCKED"):
        raise BadRequest("Mzigo umeshasafirishwa: hariri taarifa za mpokeaji badala ya kumfuta")
    if status == "PARKING":
        InvoiceDao(db).change_status(invoice, "OPEN", stamp("OPEN"), commit=False)
    return dao.delete(receiver)
