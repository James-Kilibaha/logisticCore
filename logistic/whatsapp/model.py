from sqlalchemy import Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from ..core.base_model import EntityBase


class WhatsappMessage(EntityBase):
    """
    Mazungumzo ya WhatsApp (inbox): ujumbe ULIOINGIA kutoka kwa wateja (webhook ya Meta) na majibu
    yaliyotumwa kutoka kwenye inbox. Ujumbe unaotumwa na mfumo (ankara, risiti ...) unabaki kwenye `sms`
    (channel=WHATSAPP) na unaonyeshwa pamoja kwenye mazungumzo.
    """
    __tablename__ = "whatsapp_messages"

    phone = Column(String, nullable=False)         # +255XXXXXXXXX
    profileName = Column(String, nullable=True)    # jina la WhatsApp la mteja
    direction = Column(String, nullable=False)     # IN | OUT
    kind = Column(String, nullable=False, default="text")  # text, image, document, audio, video, location ...
    text = Column(Text, nullable=True)
    mediaId = Column(String, nullable=True)
    mimeType = Column(String, nullable=True)
    fileName = Column(String, nullable=True)
    wamid = Column(String, nullable=True)          # id ya ujumbe ya Meta
    status = Column(String, nullable=True)         # IN: RECEIVED · OUT: SENT, DELIVERED, READ, FAILED
    error = Column(String, nullable=True)
    sentAt = Column(DateTime, nullable=True)       # muda wa ujumbe (kwa IN: muda wa Meta)
    readAt = Column(DateTime, nullable=True)       # IN: mtumiaji wa kampuni ameusoma kwenye inbox
    user_id = Column(UUID(as_uuid=True), nullable=True)  # OUT: aliyejibu

    __table_args__ = (Index("ix_whatsapp_messages_phone", "company_id", "phone", "created_at"),
                      Index("ix_whatsapp_messages_wamid", "wamid"),
                      Index("ix_whatsapp_messages_unread", "company_id", "direction", "readAt"))
