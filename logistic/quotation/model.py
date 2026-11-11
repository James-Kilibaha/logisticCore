from sqlalchemy import Column, Date, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import AuditedEntity


class Quotation(AuditedEntity):
    """Makadirio ya bei kwa mteja (kabla mzigo haujapokelewa). Yakikubaliwa yanageuzwa kuwa ankara."""
    __tablename__ = "quotations"

    number = Column(String, nullable=False)
    status = Column(String, nullable=False, default="DRAFT")  # DRAFT, SENT, ACCEPTED, REJECTED, CONVERTED
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    customerName = Column(String, nullable=False)
    phoneNumber = Column(String, nullable=True)
    validUntil = Column(Date, nullable=True)
    note = Column(String, nullable=True)
    total = Column(Float, nullable=False, default=0)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True)
    office_id = Column(UUID(as_uuid=True), ForeignKey("offices.id", ondelete="SET NULL"), nullable=True)

    items = relationship("QuotationItem", back_populates="quotation", cascade="all, delete-orphan",
                         order_by="QuotationItem.position")

    __table_args__ = (Index("ix_quotation_status", "status", "created_at"), Index("ux_quotations_number", "company_id", "number", unique=True))


class QuotationItem(AuditedEntity):
    __tablename__ = "quotation_items"

    quotation_id = Column(UUID(as_uuid=True), ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False)
    position = Column(Float, nullable=False, default=0)
    description = Column(String, nullable=False)
    carrierType = Column(String, nullable=False, default="AIR")  # AIR (kg) / SEA (CBM, tani)
    quantities = Column(Float, nullable=False, default=1)       # katoni
    weight = Column(Float, nullable=False, default=0)           # kg
    cbm = Column(Float, nullable=False, default=0)              # ujazo wote (m3)
    length = Column(Float, nullable=True)
    width = Column(Float, nullable=True)
    height = Column(Float, nullable=True)
    price_id = Column(UUID(as_uuid=True), ForeignKey("prices.id", ondelete="SET NULL"), nullable=True)
    unit = Column(String, nullable=False, default="KG")         # KG / CBM (kipimo cha bei)
    rate = Column(Float, nullable=False, default=0)             # TSh kwa kipimo kimoja
    amount = Column(Float, nullable=False, default=0)           # TSh

    quotation = relationship("Quotation", back_populates="items")
