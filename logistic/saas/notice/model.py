from sqlalchemy import JSON, Column, Index, String
from sqlalchemy.dialects.postgresql import UUID

from ...core.base_model import PlatformEntity


class PlatformNotice(PlatformEntity):
    """Taarifa (🔔) kwa wasimamizi wa mfumo: malipo mapya, kampuni mpya, tiketi, matatizo ya server ..."""
    __tablename__ = "platform_notices"

    kind = Column(String, nullable=False)        # PAYMENT_SUBMITTED, ONLINE_PAID, SIGNUP, TICKET, EXPIRING, SYSTEM ...
    area = Column(String, nullable=False)        # PAYMENTS | COMPANIES | SUPPORT | SYSTEM (inaamua nani anaiona)
    priority = Column(String, nullable=False, default="NORMAL")  # URGENT (popup) | NORMAL
    title = Column(String, nullable=False)
    body = Column(String, nullable=True)
    link = Column(String, nullable=True)         # payments | payment:<id> | company:<id> | ticket:<id> | onlinepay | system
    company_id = Column(UUID(as_uuid=True), nullable=True)
    dedupeKey = Column(String, nullable=True)
    readBy = Column(JSON, nullable=True)         # [admin_id, ...] waliokwisha kuisoma

    __table_args__ = (Index("ix_platform_notices_created", "created_at"),
                      Index("ix_platform_notices_dedupe", "dedupeKey", "created_at"))
