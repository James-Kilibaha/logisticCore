from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from ..core.base_model import AuditedEntity

CLAIM_TYPES = ("DAMAGED", "LOST", "SHORT")            # imeharibika, imepotea, katoni pungufu
CLAIM_STATUSES = ("OPEN", "APPROVED", "REJECTED", "SETTLED")
SETTLEMENTS = ("NONE", "DISCOUNT", "REFUND")           # fidia: hakuna / kupunguza deni / kurudisha pesa


class CargoClaim(AuditedEntity):
    """Dai la mzigo ulioharibika, kupotea au kupungua - pamoja na picha, fidia na uamuzi wake."""
    __tablename__ = "cargo_claims"

    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    type = Column(String, nullable=False)
    cartons = Column(Float, nullable=True)
    description = Column(String, nullable=False)
    photoPath = Column(String, nullable=True)
    status = Column(String, nullable=False, default="OPEN")
    compensation = Column(Float, nullable=False, default=0.0)   # TSh
    settlement = Column(String, nullable=False, default="NONE")
    resolution = Column(String, nullable=True)
    resolvedBy = Column(UUID(as_uuid=True), nullable=True)
    resolvedAt = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_claims_invoice", "invoice_id"), Index("ix_claims_status", "status"))
