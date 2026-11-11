from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ...audit.model import AuditLog
from ..company.model import Company


class MonitorDao:
    """Queries za super admin juu ya data ya kampuni (hali ya "system": hakuna kuchuja kwa kampuni)."""

    def __init__(self, db: Session):
        self.db = db

    def count(self, model, company_id, since: datetime | None = None) -> int:
        q = self.db.query(func.count(model.id)).filter(model.company_id == company_id)
        if since is not None:
            q = q.filter(model.created_at >= since)
        return int(q.scalar() or 0)

    def total(self, column, company_id, since: datetime | None = None) -> float:
        model = column.class_
        q = self.db.query(func.coalesce(func.sum(column), 0)).filter(model.company_id == company_id)
        if since is not None:
            q = q.filter(model.created_at >= since)
        return float(q.scalar() or 0)

    def audit_count(self, company_id, since: datetime) -> int:
        return int(self.db.query(func.count(AuditLog.id))
                   .filter(AuditLog.company_id == company_id, AuditLog.created_at >= since).scalar() or 0)

    def last_audit(self, company_id, action: str | None = None) -> AuditLog | None:
        q = self.db.query(AuditLog).filter(AuditLog.company_id == company_id)
        if action:
            q = q.filter(AuditLog.action == action, AuditLog.status_code < 400)
        return q.order_by(AuditLog.created_at.desc()).first()

    def activity(self, company_id=None, q: str | None = None, module: str | None = None,
                 failed: bool | None = None, offset: int = 0, limit: int = 100, kind: str | None = None):
        query = (self.db.query(AuditLog, Company.name, Company.slug)
                 .outerjoin(Company, Company.id == AuditLog.company_id))
        if company_id:
            query = query.filter(AuditLog.company_id == company_id)
        if module:
            query = query.filter(AuditLog.module == module)
        if kind == "views":
            query = query.filter(AuditLog.action == "VIEW")
        elif kind == "actions":
            query = query.filter(AuditLog.action != "VIEW")
        if failed is not None:
            query = query.filter(AuditLog.status_code >= 400 if failed else AuditLog.status_code < 400)
        if q:
            like = f"%{q.strip()}%"
            query = query.filter(or_(AuditLog.username.ilike(like), AuditLog.summary.ilike(like),
                                     AuditLog.entity_id.ilike(like), AuditLog.path.ilike(like),
                                     Company.name.ilike(like), Company.slug.ilike(like)))
        total = query.count()
        rows = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
        return total, rows

    def active_companies_since(self, since: datetime) -> dict:
        """company_id -> idadi ya vitendo tangu `since` (kampuni zinazotumia mfumo sasa)."""
        rows = (self.db.query(AuditLog.company_id, func.count(AuditLog.id), func.max(AuditLog.created_at))
                .filter(AuditLog.company_id.isnot(None), AuditLog.created_at >= since)
                .group_by(AuditLog.company_id).all())
        return {r[0]: (int(r[1]), r[2]) for r in rows}
