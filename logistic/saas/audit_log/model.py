from sqlalchemy import Column, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from ...core.base_model import PlatformEntity


class PlatformAuditLog(PlatformEntity):
    """Kila kitendo cha super admin: kuingia, kuidhinisha, kusimamisha, malipo, kuingia kama kampuni ..."""
    __tablename__ = "platform_audit_logs"

    admin_id = Column(UUID(as_uuid=True), nullable=True)
    username = Column(String, nullable=True)
    action = Column(String, nullable=False)          # LOGIN, COMPANY_APPROVE, VIEW_AS, PAYMENT_CONFIRM ...
    method = Column(String, nullable=True)
    path = Column(String, nullable=True)
    company_id = Column(UUID(as_uuid=True), nullable=True)  # kampuni iliyoguswa (kama ipo)
    summary = Column(String, nullable=True)
    detail = Column(Text, nullable=True)             # data iliyotumwa (bila nywila / siri)
    ip = Column(String, nullable=True)
    statusCode = Column(Integer, nullable=True)

    __table_args__ = (Index("ix_platform_audit_created", "created_at"),
                      Index("ix_platform_audit_company", "company_id", "created_at"))
