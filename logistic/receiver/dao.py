from sqlalchemy.orm import joinedload

from ..core.dao import BaseDao, to_uuid
from .model import Receiver


class ReceiverDao(BaseDao[Receiver]):
    model = Receiver

    def by_track_number(self, track: str) -> Receiver | None:
        return self.find_one(Receiver.trackNumber == track)

    def by_invoice(self, invoice_id) -> Receiver | None:
        return self.find_one(Receiver.invoice_id == to_uuid(invoice_id), options=[joinedload(Receiver.invoice)])

    def by_phone(self, phone: str | None) -> Receiver | None:
        return self.find_one(Receiver.phoneNumber == phone) if phone else None

    def not_blocked(self) -> list[Receiver]:
        return self.find_all(Receiver.active == 1, options=[joinedload(Receiver.invoice)])
