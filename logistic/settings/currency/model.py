from sqlalchemy import Column, Float, String
from sqlalchemy.orm import relationship

from ...core.base_model import AuditedEntity


class Currency(AuditedEntity):
    """Kiwango cha sarafu (mfano USD -> TSHS). Kiwango kipya kikiwekwa, cha zamani kinazuiwa (isBlocked)."""
    __tablename__ = "currents"

    name = Column(String, nullable=False)
    rate = Column(Float, nullable=False, default=1.0)
    local = Column(String, nullable=False, default="TSHS")
    buy = Column(Float, nullable=False)

    price = relationship("Price", back_populates="currency", uselist=True)
