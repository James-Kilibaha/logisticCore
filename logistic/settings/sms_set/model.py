from sqlalchemy import Boolean, Column, Index, String

from ...core.base_model import EntityBase


class SmsSet(EntityBase):
    """Kuwasha/kuzima kila aina ya SMS (tazama core.enums.ESmsStatus) - aina iliyozimwa haitumwi kabisa."""
    __tablename__ = "smsSet"

    name = Column(String, nullable=False)
    action = Column(Boolean, default=False, nullable=False)

    __table_args__ = (Index("ux_smsSet_name", "company_id", "name", unique=True),)
