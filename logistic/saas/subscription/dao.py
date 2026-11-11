from ...core.base_model import utc_now
from ...core.dao import BaseDao
from .model import Subscription, SubscriptionPayment


class SubscriptionDao(BaseDao[Subscription]):
    model = Subscription

    def for_company(self, company_id) -> list[Subscription]:
        return (self.query().filter(Subscription.company_id == company_id)
                .order_by(Subscription.endsAt.desc()).all())

    def active_periods(self, company_id) -> list[Subscription]:
        return (self.query().filter(Subscription.company_id == company_id, Subscription.status != "CANCELLED")
                .order_by(Subscription.endsAt.desc()).all())

    def covering_now(self, company_id) -> Subscription | None:
        now = utc_now()
        return (self.query().filter(Subscription.company_id == company_id, Subscription.status != "CANCELLED",
                                    Subscription.startsAt <= now, Subscription.endsAt >= now)
                .order_by(Subscription.startsAt.desc()).first())

    def latest(self, company_id) -> Subscription | None:
        rows = self.active_periods(company_id)
        return rows[0] if rows else None


class PaymentDao(BaseDao[SubscriptionPayment]):
    model = SubscriptionPayment

    def for_company(self, company_id, limit: int = 100) -> list[SubscriptionPayment]:
        return (self.query().filter(SubscriptionPayment.company_id == company_id)
                .order_by(SubscriptionPayment.created_at.desc()).limit(limit).all())

    def search(self, status: str | None = None, company_id=None, limit: int = 200) -> list[SubscriptionPayment]:
        q = self.query()
        if status:
            q = q.filter(SubscriptionPayment.status == status)
        if company_id:
            q = q.filter(SubscriptionPayment.company_id == company_id)
        return q.order_by(SubscriptionPayment.created_at.desc()).limit(limit).all()
