from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from ...core.base_model import PlatformEntity


class SupportTicket(PlatformEntity):
    __tablename__ = "support_tickets"

    number = Column(Integer, nullable=False)               # T-000123
    company_id = Column(UUID(as_uuid=True), nullable=False)
    subject = Column(String, nullable=False)
    category = Column(String, nullable=False, default="TECH")   # TECH | BILLING | FEATURE | OTHER
    priority = Column(String, nullable=False, default="NORMAL")  # NORMAL | HIGH
    status = Column(String, nullable=False, default="OPEN")      # OPEN | ANSWERED | CLOSED
    user_id = Column(UUID(as_uuid=True), nullable=True)          # aliyefungua (mtumiaji wa kampuni)
    username = Column(String, nullable=True)
    lastMessageAt = Column(DateTime, nullable=True)
    unreadAdmin = Column(Boolean, nullable=False, default=True, server_default="true")
    unreadCompany = Column(Boolean, nullable=False, default=False, server_default="false")
    closedAt = Column(DateTime, nullable=True)

    __table_args__ = (Index("ux_support_tickets_number", "number", unique=True),
                      Index("ix_support_tickets_company", "company_id", "lastMessageAt"))


class TicketMessage(PlatformEntity):
    __tablename__ = "support_messages"

    ticket_id = Column(UUID(as_uuid=True), nullable=False)
    author = Column(String, nullable=False)        # COMPANY | ADMIN
    username = Column(String, nullable=True)
    text = Column(Text, nullable=False)

    __table_args__ = (Index("ix_support_messages_ticket", "ticket_id", "created_at"),)
