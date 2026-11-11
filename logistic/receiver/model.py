from sqlalchemy import Index, Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import AuditedEntity


class Receiver(AuditedEntity):
    """Mpokeaji wa mzigo wa ankara (invoice) moja."""
    __tablename__ = "receivers"

    name = Column(String, nullable=False)
    phoneNumber = Column(String, nullable=True)  # +255XXXXXXXXX au NULL
    trackNumber = Column(String, nullable=False)
    active = Column(Integer, nullable=False, default=1)

    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"))
    invoice = relationship("Invoice", back_populates="receiver", uselist=True)

    __table_args__ = (Index("ix_receivers_invoice", "invoice_id"), Index("ux_receivers_tracknumber", "company_id", "trackNumber", unique=True))
