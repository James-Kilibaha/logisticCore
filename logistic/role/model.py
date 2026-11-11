from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import EntityBase


class Role(EntityBase):
    """
    Jukumu (role) lenye seti ya ruhusa: mf. Msimamizi, Mhasibu, Stoo, Mpokeaji China, Mtazamaji.
    Mtumiaji akipewa role, ruhusa za role zinanakiliwa kwenye ruhusa zake (jedwali la permissions).
    """
    __tablename__ = "roles"

    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    isSystem = Column(Boolean, nullable=False, default=False)  # role za mfumo (haziwezi kufutwa)
    # toleo la ruhusa za kuanzia lililokwisha wekwa (role za mfumo zinapata ruhusa za vipengele vipya mara moja tu)
    defaultsVersion = Column(Integer, nullable=False, default=0, server_default="0")

    permissions = relationship("RolePermission", back_populates="role", cascade="all, delete-orphan",
                               order_by="RolePermission.module")

    __table_args__ = (Index("ux_roles_name", "company_id", "name", unique=True),)


class RolePermission(EntityBase):
    __tablename__ = "role_permissions"

    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    module = Column(String, nullable=False)
    data_insert = Column(Boolean, nullable=False, default=False)
    data_update = Column(Boolean, nullable=False, default=False)
    data_select = Column(Boolean, nullable=False, default=False)
    data_delete = Column(Boolean, nullable=False, default=False)
    data_block = Column(Boolean, nullable=False, default=False)

    role = relationship("Role", back_populates="permissions")

    __table_args__ = (UniqueConstraint("role_id", "module", name="uq_role_module"),)
