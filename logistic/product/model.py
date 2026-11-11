from sqlalchemy import Index, Column, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import AuditedEntity


class Product(AuditedEntity):
    """Mzigo/bidhaa ndani ya invoice. `unitPrice` ni gharama yote ya mstari huu."""
    __tablename__ = "products"

    description = Column(String, nullable=False)
    unitPrice = Column(Float, nullable=False)
    quantities = Column(Float, nullable=False)
    weight = Column(Float, nullable=False)
    trackNumber = Column(String, nullable=True)

    carrierType = Column(String, nullable=False)  # AIR / SEA
    length = Column(Float, nullable=True)
    width = Column(Float, nullable=True)
    height = Column(Float, nullable=True)

    path = Column(String, nullable=True)  # picha ya bidhaa
    # Code ya ofisi: inatumwa kwa SMS na kuchapishwa kwenye lebo; mpokeaji anaionyesha kuchukua mzigo huu.
    officeCode = Column(String, nullable=True)

    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"))
    price_id = Column(UUID(as_uuid=True), ForeignKey("prices.id", ondelete="CASCADE"))

    invoice = relationship("Invoice", back_populates="product", uselist=True)
    price = relationship("Price", back_populates="product", uselist=True)

    __table_args__ = (Index("ix_products_invoice", "invoice_id"), Index("ix_products_track", "trackNumber"),
                      Index("ux_products_company_office_code", "company_id", "officeCode", unique=True))
