from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import AuditedEntity


class CashUp(AuditedEntity):
    """
    Kufunga hesabu ya siku: kwa kila njia ya malipo, kiasi ambacho mfumo unaonyesha (expected) dhidi ya
    kiasi halisi kilichohesabiwa (counted). `logsId` = aliyefunga.
    """
    __tablename__ = "cashups"

    day = Column(String, nullable=False)          # YYYY-MM-DD (saa za hapa)
    office_id = Column(UUID(as_uuid=True), ForeignKey("offices.id", ondelete="SET NULL"), nullable=True)
    expected = Column(Float, nullable=False, default=0.0)
    counted = Column(Float, nullable=False, default=0.0)
    difference = Column(Float, nullable=False, default=0.0)  # counted - expected
    payments = Column(Integer, nullable=False, default=0)
    note = Column(String, nullable=True)
    closedAt = Column(DateTime, nullable=False)

    lines = relationship("CashUpLine", back_populates="cashup", cascade="all, delete-orphan")

    __table_args__ = (Index("ux_cashups_company_day_office", "company_id", "day", "office_id", unique=True), Index("ix_cashups_day", "day"))


class CashUpLine(AuditedEntity):
    __tablename__ = "cashup_lines"

    cashup_id = Column(UUID(as_uuid=True), ForeignKey("cashups.id", ondelete="CASCADE"), nullable=False)
    institute_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="SET NULL"), nullable=True)
    name = Column(String, nullable=False)          # jina la njia wakati wa kufunga
    expected = Column(Float, nullable=False, default=0.0)
    counted = Column(Float, nullable=False, default=0.0)
    difference = Column(Float, nullable=False, default=0.0)
    payments = Column(Integer, nullable=False, default=0)
    note = Column(String, nullable=True)

    cashup = relationship("CashUp", back_populates="lines")

    __table_args__ = (Index("ix_cashup_lines_cashup", "cashup_id"),)
