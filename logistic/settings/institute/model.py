from sqlalchemy import Column, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ...core.base_model import AuditedEntity


class Institute(AuditedEntity):
    """Taasisi ya fedha (benki / mobile money) inayopokea malipo."""
    __tablename__ = "institutes"

    name = Column(String, nullable=False)
    accountNo = Column(String, nullable=False)
    currencyType = Column(String, nullable=False)
    # v2.15 uhasibu: taasisi = akaunti ya fedha
    kind = Column(String, nullable=False, default="BANK", server_default="BANK")   # CASH | BANK | MOBILE
    openingBalance = Column(Float, nullable=False, default=0.0, server_default="0")  # TSh
    openingDate = Column(String, nullable=True)   # YYYY-MM-DD: salio la kuanzia ni la mwanzo wa siku hii
    office_id = Column(UUID(as_uuid=True), ForeignKey("offices.id", ondelete="SET NULL"), nullable=True)

    payment = relationship("Payment", back_populates="institute", uselist=True)

    __table_args__ = (Index("ux_institutes_accountno", "company_id", "accountNo", unique=True),)
