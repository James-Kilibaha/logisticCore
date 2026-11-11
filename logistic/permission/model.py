from sqlalchemy import Boolean, Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import AuditedEntity


class Permission(AuditedEntity):
    __tablename__ = "permissions"

    # NB: (id, name) ni primary key ya pamoja kama ilivyo kwenye database iliyopo.
    name = Column(String, primary_key=True)
    data_insert = Column(Boolean, default=False, nullable=False)
    data_update = Column(Boolean, default=False, nullable=False)
    data_select = Column(Boolean, default=False, nullable=False)
    data_block = Column(Boolean, default=False, nullable=False)
    data_delete = Column(Boolean, default=False, nullable=False)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user = relationship("User", back_populates="permission")
