from sqlalchemy import Column, String
from sqlalchemy.orm import relationship

from ...core.base_model import AuditedEntity


class Office(AuditedEntity):
    __tablename__ = "offices"

    name = Column(String, nullable=False)
    location = Column(String, nullable=False)
    phoneNumber = Column(String, nullable=True)

    expense = relationship("Expense", back_populates="office", uselist=True)
    user = relationship("User", back_populates="office", uselist=True)
