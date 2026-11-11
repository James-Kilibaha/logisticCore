"""
Columns zinazoshirikiwa na tables zote.

- `EntityBase`   : id, company_id, isBlocked, created_at, update_at
                   (company_id = kampuni mwenye data - inachujwa yenyewe, tazama core/tenant.py)
- `AuditedEntity`: kama EntityBase + logsId (mtumiaji aliyeunda rekodi)
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declared_attr

from ..db import Base


def utc_now() -> datetime:
    # Tunahifadhi muda wa UTC bila timezone (kama ilivyokuwa awali).
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EntityBase(Base):
    __abstract__ = True

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    @declared_attr
    def company_id(cls):
        # Kampuni (tenant) mwenye rekodi. Inawekwa yenyewe kabla ya kuhifadhi (db.py).
        return Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)

    isBlocked = Column(Boolean, nullable=False, default=False)
    # Callable (si utc_now()) ili kila rekodi ipate muda wake halisi.
    update_at = Column(DateTime, onupdate=utc_now)
    created_at = Column(DateTime, default=utc_now)


class AuditedEntity(EntityBase):
    __abstract__ = True

    logsId = Column(UUID(as_uuid=True), nullable=False)


class PlatformEntity(Base):
    """Tables za mfumo mzima (kampuni, mipango, subscription) - hazina company_id na hazichujwi."""
    __abstract__ = True

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    update_at = Column(DateTime, onupdate=utc_now)
    created_at = Column(DateTime, default=utc_now)
