from sqlalchemy import Column, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import AuditedEntity


class Invoice(AuditedEntity):
    """
    Ankara ya mteja. `status` inafuata EInvoiceStatus na `history` ni orodha
    (iliyotenganishwa kwa koma) ya mabadiliko yote ya hali.
    """
    __tablename__ = "invoices"

    invoiceNumber = Column(String, nullable=False)
    status = Column(String, nullable=False)
    history = Column(String, nullable=False)
    path = Column(String, nullable=True)  # PDF ya invoice (bila .pdf)

    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"))
    # Ofisi ya kuchukulia mzigo (tawi). NULL = haijapangiwa (inaonekana kwa ofisi zote).
    office_id = Column(UUID(as_uuid=True), ForeignKey("offices.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        Index("ux_invoices_invoicenumber", "company_id", "invoiceNumber", unique=True),
        Index("ix_invoices_status", "status"),
        Index("ix_invoices_customer", "customer_id"),
        Index("ix_invoices_office", "office_id"),
        Index("ix_invoices_created", "created_at"),
    )

    customer = relationship("Customer", back_populates="invoice", uselist=True)
    product = relationship("Product", back_populates="invoice", uselist=True)
    receiver = relationship("Receiver", back_populates="invoice", uselist=True)
    debt = relationship("Debt", back_populates="invoice", uselist=True)
    sms = relationship("Sms", back_populates="invoice", uselist=True)
    handover = relationship("Handover", back_populates="invoice", uselist=True)
