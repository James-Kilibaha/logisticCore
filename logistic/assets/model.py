"""Mali za kudumu (gari, kompyuta, samani, jengo ...) na uchakavu wake (straight-line kwa mwezi)."""
from sqlalchemy import Column, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from ..core.base_model import AuditedEntity

ASSET_CATEGORIES = ("VEHICLE", "COMPUTER", "FURNITURE", "EQUIPMENT", "BUILDING", "OTHER")


class FixedAsset(AuditedEntity):
    __tablename__ = "fixed_assets"

    name = Column(String, nullable=False)
    category = Column(String, nullable=False, default="OTHER")
    cost = Column(Float, nullable=False)                       # TSh
    currency = Column(String, nullable=False, default="TZS", server_default="TZS")
    amountOriginal = Column(Float, nullable=True)
    rate = Column(Float, nullable=True)
    purchaseDate = Column(String, nullable=False)              # YYYY-MM-DD
    lifeMonths = Column(Integer, nullable=False, default=60)   # muda wa matumizi (miezi)
    salvage = Column(Float, nullable=False, default=0.0)       # thamani ya mwisho (TSh)
    institute_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="SET NULL"), nullable=True)
    office_id = Column(UUID(as_uuid=True), ForeignKey("offices.id", ondelete="SET NULL"), nullable=True)
    serial = Column(String, nullable=True)
    note = Column(String, nullable=True)
    disposedOn = Column(String, nullable=True)                 # YYYY-MM-DD (imeuzwa / imeharibika)
    disposalAmount = Column(Float, nullable=True)              # TSh iliyopatikana
    disposal_institute_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (Index("ix_fixed_assets_purchase", "purchaseDate"),)
