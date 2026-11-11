from sqlalchemy import func, or_

from ...core.dao import BaseDao
from .model import Company


class CompanyDao(BaseDao[Company]):
    model = Company

    def by_slug(self, slug: str | None) -> Company | None:
        if not slug:
            return None
        return self.find_one(func.lower(Company.slug) == slug.strip().lower())

    def by_domain(self, domain: str | None) -> Company | None:
        if not domain:
            return None
        return self.find_one(func.lower(Company.domain) == domain.strip().lower())

    def search(self, q: str | None = None, status: str | None = None, offset: int = 0, limit: int = 100):
        query = self.query()
        if q:
            like = f"%{q.strip().lower()}%"
            query = query.filter(or_(func.lower(Company.name).like(like), func.lower(Company.slug).like(like),
                                     func.lower(Company.phone).like(like), func.lower(Company.domain).like(like),
                                     func.lower(Company.ownerName).like(like)))
        if status:
            query = query.filter(Company.status == status)
        total = query.count()
        rows = query.order_by(Company.created_at.desc()).offset(offset).limit(limit).all()
        return rows, total
