from sqlalchemy import JSON, Boolean, Column, DateTime, Index, Integer, String

from ...core.base_model import PlatformEntity


class PlatformAdmin(PlatformEntity):
    """Wewe na wasaidizi wako: wanaosimamia kampuni zote, mipango na malipo (admin panel ya juu)."""
    __tablename__ = "platform_admins"

    username = Column(String, nullable=False)
    password = Column(String, nullable=False)  # argon2
    fullName = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    # OWNER (kila kitu) | FINANCE (malipo, subscription, mipango) | SUPPORT (kampuni, msaada, kuingia kama kampuni)
    # | VIEWER (kusoma tu). Tazama saas/admin/roles.py
    role = Column(String, nullable=False, default="OWNER", server_default="OWNER")
    tokenVersion = Column(Integer, nullable=False, default=0, server_default="0")
    lastLoginAt = Column(DateTime, nullable=True)
    # Kusahau nywila: code ya tarakimu 6 (hash tu) inayotumwa kwa SMS/email
    otpHash = Column(String, nullable=True)
    otpExpires = Column(DateTime, nullable=True)
    otpSentAt = Column(DateTime, nullable=True)
    otpAttempts = Column(Integer, nullable=False, default=0, server_default="0")
    # Uthibitisho wa hatua mbili (TOTP - app ya Authenticator)
    totpEnabled = Column(Boolean, nullable=False, default=False, server_default="false")
    totpSecret = Column(String, nullable=True)
    totpPendingSecret = Column(String, nullable=True)   # wakati wa kuunganisha (kabla ya kuthibitisha code)
    totpRecovery = Column(JSON, nullable=True)           # hash za code za dharura ambazo bado hazijatumika
    totpLastCounter = Column(Integer, nullable=True)     # code iliyotumika mwisho (haitumiki tena)

    __table_args__ = (Index("ux_platform_admins_username", "username", unique=True),)
