from ..core.dao import BaseDao, to_uuid
from .model import Handover


class HandoverDao(BaseDao[Handover]):
    model = Handover

    def by_invoice(self, invoice_id) -> Handover | None:
        return self.find_one(Handover.invoice_id == to_uuid(invoice_id))
