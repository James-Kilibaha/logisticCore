from sqlalchemy import Boolean, Column, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from ...core.base_model import PlatformEntity


class Plan(PlatformEntity):
    """
    Mpango wa subscription (mf. Starter / Business / Enterprise).

    Mipaka (NULL = hakuna kikomo): watumiaji, ofisi (matawi), ankara kwa mwezi.
    `modules`: orodha ya moduli za ziada zinazoruhusiwa (tazama OPTIONAL_MODULES); NULL = zote.
    """
    __tablename__ = "plans"

    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False, default=0)
    currency = Column(String, nullable=False, default="TZS", server_default="TZS")
    months = Column(Integer, nullable=False, default=1, server_default="1")   # muda wa malipo moja

    maxUsers = Column(Integer, nullable=True)
    maxOffices = Column(Integer, nullable=True)
    maxInvoicesPerMonth = Column(Integer, nullable=True)
    modules = Column(JSONB, nullable=True)

    isPublic = Column(Boolean, nullable=False, default=True, server_default="true")   # inaonekana kwa wateja
    isActive = Column(Boolean, nullable=False, default=True, server_default="true")
    sortOrder = Column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (Index("ux_plans_code", "code", unique=True),)
