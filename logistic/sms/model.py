from sqlalchemy import Index, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import AuditedEntity, EntityBase


class Sms(AuditedEntity):
    """SMS iliyoandaliwa na mfumo; inatumwa kwa mteja kutoka kwenye app (/api/sms/send)."""
    __tablename__ = "sms"

    text = Column(String, nullable=False)
    msisdn = Column(String, nullable=False)
    source = Column(String, nullable=False)
    reference = Column(String, nullable=False)
    coding = Column(String, nullable=False)
    smsFor = Column(String, nullable=False)
    isReceived = Column(Boolean, nullable=False, default=False)
    isSMSSend = Column(Boolean, nullable=False, default=False)
    channel = Column(String, nullable=False, default="SMS", server_default="SMS")  # SMS au WHATSAPP
    error = Column(String, nullable=True)  # sababu ya mwisho ya kushindwa kutuma
    # Ripoti ya kufika (DLR) kutoka FastHub / WhatsApp: SENT (gateway imepokea), DELIVERED, FAILED; tupu = haijulikani
    deliveryStatus = Column(String, nullable=True)
    deliveredAt = Column(DateTime, nullable=True)
    gatewayRef = Column(String, nullable=True)  # reference yetu iliyotumwa kwa gateway (ya kipekee)
    gatewayId = Column(String, nullable=True)   # id ya ujumbe kutoka gateway (mf. wamid ya WhatsApp)
    sentAt = Column(DateTime, nullable=True)    # ilipokabidhiwa kwa gateway
    parts = Column(Integer, nullable=True)      # vipande vya SMS vilivyotumika (salio)
    balanceAfter = Column(Float, nullable=True)  # salio la FastHub baada ya kutuma ujumbe huu (jibu la gateway)
    gatewayResponse = Column(Text, nullable=True)  # jibu kamili la FastHub la mara ya mwisho (uchunguzi)

    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"))
    invoice = relationship("Invoice", back_populates="sms", uselist=True)

    __table_args__ = (Index("ix_sms_invoice", "invoice_id"), Index("ix_sms_pending", "isSMSSend", "created_at"),
                      Index("ix_sms_gateway_ref", "gatewayRef"), Index("ix_sms_gateway_id", "gatewayId"),
                      Index("ix_sms_sent_at", "sentAt"))


class SmsCredit(AuditedEntity):
    """
    Salio la SMS (FastHub) linalofuatiliwa ndani ya mfumo:
      SET = salio halisi kwa wakati huu (kutoka akaunti ya FastHub), ADD = SMS zilizonunuliwa.
    Salio linalokadiriwa = SET ya mwisho + ADD baada yake - vipande vya SMS vilivyotumwa baada yake.
    """
    __tablename__ = "sms_credits"

    kind = Column(String, nullable=False)  # SET / ADD
    amount = Column(Integer, nullable=False)
    note = Column(String, nullable=True)


class AutoSmsRule(EntityBase):
    """
    SMS za moja kwa moja (vikumbusho) - admin anaweka kwa kila aina:
      afterDays  : ianze baada ya siku ngapi (STORAGE_WARN: siku ngapi kabla siku za bure hazijaisha)
      everyDays  : ijirudie kila siku ngapi (0 = mara moja tu)
      autoSend   : itumwe yenyewe (True) au isubiri mtu abonyeze "Tuma" (False)
      hour       : saa ya siku (saa za ofisi) ya kuandaa/kutuma
    """
    __tablename__ = "auto_sms_rules"

    kind = Column(String, nullable=False)  # ya kipekee ndani ya kampuni (tazama __table_args__)
    enabled = Column(Boolean, nullable=False, default=True)
    afterDays = Column(Integer, nullable=False, default=7)
    everyDays = Column(Integer, nullable=False, default=7)
    autoSend = Column(Boolean, nullable=False, default=True)
    hour = Column(Integer, nullable=False, default=9)
    lastRunOn = Column(Date, nullable=True)  # siku ya mwisho kazi hii ilipoendeshwa na scheduler

    __table_args__ = (Index("ux_auto_sms_rules_company_kind", "company_id", "kind", unique=True),)
