from sqlalchemy import Boolean, Column, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from ..core.base_model import EntityBase


class Notification(EntityBase):
    """Taarifa ndani ya app (🔔) kwa mtumiaji mmoja."""
    __tablename__ = "notifications"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String, nullable=False)          # BOX_SHIPPED, BOX_ARRIVED, PAYMENT, CLAIM, DEBT_OLD, ALERT ...
    title = Column(String, nullable=False)
    body = Column(String, nullable=True)
    link = Column(String, nullable=True)           # invoice:<id>, box:<id>, claims, settings
    isRead = Column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_notifications_user", "user_id", "isRead", "created_at"),)
