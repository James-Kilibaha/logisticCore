from sqlalchemy.orm import joinedload

from ..core.dao import BaseDao
from ..invoice.model import Invoice
from .model import Sms


class SmsDao(BaseDao[Sms]):
    model = Sms

    def search(self, sms_for: str | None, is_received: bool, is_sent: bool | None, channel: str | None = None,
               delivery: str | None = None, since=None, limit: int | None = None) -> list[Sms]:
        criteria = [Sms.isReceived == is_received]
        if is_sent is not None:
            criteria.append(Sms.isSMSSend == is_sent)
        if since is not None:
            criteria.append(Sms.created_at >= since)
        if delivery:
            criteria.append(Sms.deliveryStatus == delivery.upper())
        if sms_for is not None:
            criteria.append(Sms.smsFor == sms_for)
        if channel is not None:
            criteria.append(Sms.channel == channel.upper())
        q = (self.query(joinedload(Sms.invoice).joinedload(Invoice.customer)).filter(*criteria)
             .order_by(Sms.created_at.desc()))
        if limit:
            q = q.limit(limit)
        return q.all()

    def pending_since(self, since) -> list[Sms]:
        return self.find_all(Sms.isSMSSend.is_(False), Sms.created_at >= since, order_by=Sms.created_at)
