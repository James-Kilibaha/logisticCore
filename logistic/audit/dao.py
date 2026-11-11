from sqlalchemy import or_

from ..core.dao import BaseDao, to_uuid
from ..core.utils import day_range
from .model import AuditLog


class AuditDao(BaseDao[AuditLog]):
    model = AuditLog

    def search(self, f) -> tuple[int, list[AuditLog]]:
        q = self.query()
        if f.userId:
            q = q.filter(AuditLog.user_id == to_uuid(f.userId))
        if f.module:
            q = q.filter(AuditLog.module == f.module)
        if f.action:
            q = q.filter(AuditLog.action == f.action)
        if f.failed is not None:
            q = q.filter(AuditLog.status_code >= 400 if f.failed else AuditLog.status_code < 400)
        if f.client:
            q = q.filter(AuditLog.client == f.client.upper())
        start, end = day_range(f.startDate, f.endDate)
        if start:
            q = q.filter(AuditLog.created_at >= start)
        if end:
            q = q.filter(AuditLog.created_at < end)
        if f.q:
            like = f"%{f.q.strip()}%"
            q = q.filter(or_(AuditLog.username.ilike(like), AuditLog.summary.ilike(like), AuditLog.device.ilike(like),
                             AuditLog.entity_id.ilike(like), AuditLog.detail.ilike(like)))
        total = q.count()
        rows = q.order_by(AuditLog.created_at.desc()).offset(f.offset).limit(f.limit).all()
        return total, rows

    def modules(self) -> list[str]:
        return [r[0] for r in self.db.query(AuditLog.module).distinct().order_by(AuditLog.module)]
