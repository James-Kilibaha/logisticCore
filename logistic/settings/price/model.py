from sqlalchemy import Column, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ...core.base_model import AuditedEntity


class Price(AuditedEntity):
    """
    Bei ya usafirishaji: `cost` kwa kila `weight` ya `unit` kwa sarafu fulani.
      unit = KG  -> kwa kilo (ndege, au meli kwa uzito)
      unit = CBM -> kwa mita za ujazo (meli)
    """
    __tablename__ = "prices"

    name = Column(String, nullable=False)
    weight = Column(Float, nullable=False, default=0)
    cost = Column(Float, nullable=False, default=0)
    unit = Column(String, nullable=False, default="KG", server_default="KG")

    currency_id = Column(UUID(as_uuid=True), ForeignKey("currents.id", ondelete="CASCADE"))

    currency = relationship("Currency", back_populates="price", uselist=True)
    product = relationship("Product", back_populates="price", uselist=True)
