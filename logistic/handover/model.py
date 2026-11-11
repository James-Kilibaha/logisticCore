from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import AuditedEntity


class Handover(AuditedEntity):
    """
    Ushahidi wa kukabidhi mzigo: nani aliuchukua, kitambulisho chake, sahihi/picha na nani alimkabidhi
    (`logsId`). Ankara moja inaweza kuwa na makabidhiano kadhaa (mzigo ukichukuliwa kwa awamu);
    `items` zinaonyesha katoni zilizochukuliwa kila mara. Makabidhiano bila items = mzigo wote.
    """
    __tablename__ = "handovers"

    collectorName = Column(String, nullable=False)
    collectorPhone = Column(String, nullable=True)  # +255XXXXXXXXX au NULL
    idType = Column(String, nullable=True)      # NIDA, LESENI, MPIGA_KURA, PASIPOTI, NYINGINE
    idNumber = Column(String, nullable=True)
    isReceiver = Column(Boolean, nullable=False, default=True)  # ndiye mpokeaji aliyesajiliwa?
    onCredit = Column(Boolean, nullable=False, default=False)   # amekabidhiwa akiwa bado anadaiwa
    balance = Column(Float, nullable=False, default=0.0)        # deni lililobaki wakati wa kukabidhi
    signaturePath = Column(String, nullable=True)
    photoPath = Column(String, nullable=True)
    note = Column(String, nullable=True)
    # Code ya ofisi iliyoonyeshwa na mchukuaji ililingana (False = msimamizi aliruhusu bila code)
    codeVerified = Column(Boolean, nullable=False, default=False, server_default="false")

    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    invoice = relationship("Invoice", back_populates="handover", uselist=True)
    items = relationship("HandoverItem", back_populates="handover", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_handovers_invoice", "invoice_id"),)


class HandoverItem(AuditedEntity):
    """Katoni za bidhaa moja zilizochukuliwa kwenye makabidhiano haya."""
    __tablename__ = "handover_items"

    handover_id = Column(UUID(as_uuid=True), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    cartons = Column(Float, nullable=False)

    handover = relationship("Handover", back_populates="items")

    __table_args__ = (Index("ix_handover_items_handover", "handover_id"),)
