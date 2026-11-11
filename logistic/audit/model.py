from sqlalchemy import Column, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from ..core.base_model import EntityBase


class AuditLog(EntityBase):
    """
    Kumbukumbu ya kila kitendo kinachobadilisha data: nani, lini, nini, kutoka wapi.
    Inaandikwa yenyewe na `core/audit.py` (middleware) - hakuna service inayohitaji kuiita.
    """
    __tablename__ = "audit_logs"

    user_id = Column(UUID(as_uuid=True), nullable=True)
    username = Column(String, nullable=True)
    module = Column(String, nullable=False)        # invoice, product, settings/currency ...
    action = Column(String, nullable=False)        # CREATE, UPDATE, DELETE, BLOCK, LOGIN ...
    method = Column(String, nullable=False)
    path = Column(String, nullable=False)
    entity_id = Column(String, nullable=True)
    status_code = Column(Integer, nullable=False)
    ip = Column(String, nullable=True)
    summary = Column(String, nullable=True)        # maelezo mafupi yanayosomeka (kama yapo)
    detail = Column(Text, nullable=True)           # data iliyotumwa (bila nywila)
    client = Column(String, nullable=True)         # APP (simu/kompyuta) / WEB (browser) / API
    device = Column(String, nullable=True)         # mf. "Samsung SM-A515F · Android 13" / "Chrome 130 · Windows 10/11"

    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_module", "module"),
    )
