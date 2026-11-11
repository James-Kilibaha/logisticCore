from sqlalchemy import Column, Float, Index, Integer, String
from sqlalchemy.orm import relationship

from ..core.base_model import AuditedEntity


class Customer(AuditedEntity):
    __tablename__ = "customers"

    name = Column(String, nullable=False)
    phoneNumber = Column(String, nullable=True)  # +255XXXXXXXXX au NULL
    active = Column(Integer, nullable=False, default=1)
    # Kikomo cha mkopo (TSh): NULL = tumia DEFAULT_CREDIT_LIMIT; 0 = hakopeshwi kabisa
    creditLimit = Column(Float, nullable=True)

    invoice = relationship("Invoice", back_populates="customer", uselist=True, order_by="Invoice.invoiceNumber")

    # namba moja ya simu kwa mteja mmoja ndani ya kampuni moja
    __table_args__ = (Index("ux_customers_phonenumber", "company_id", "phoneNumber", unique=True),)
