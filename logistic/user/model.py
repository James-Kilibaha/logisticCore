from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.base_model import EntityBase


class User(EntityBase):
    __tablename__ = "users"

    firstName = Column(String, nullable=False)
    lastName = Column(String, nullable=False)
    phoneNumber = Column(String, nullable=True)  # +255XXXXXXXXX au NULL
    username = Column(String, nullable=False)
    password = Column(String, nullable=False)  # argon2 hash
    active = Column(Integer, nullable=False, default=1)
    # False = anaona data ya ofisi yake tu (tazama core/scope.py)
    allOffices = Column(Boolean, nullable=False, default=True, server_default="true")
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    # Mtumiaji mpya / aliyebadilishiwa nywila na msimamizi lazima aweke nywila yake mwenyewe.
    mustChangePassword = Column(Boolean, nullable=False, default=False, server_default="false")
    # Inaongezeka kila "toa kwenye vifaa vyote" / nywila ikibadilishwa: token za zamani zinakufa.
    tokenVersion = Column(Integer, nullable=False, default=0, server_default="0")
    # Uthibitisho wa hatua mbili: baada ya nywila, code (OTP) inatumwa kwa SMS kwenye simu yake.
    twoFactor = Column(Boolean, nullable=False, default=False, server_default="false")
    otpHash = Column(String, nullable=True)
    otpExpires = Column(DateTime, nullable=True)
    otpSentAt = Column(DateTime, nullable=True)
    otpAttempts = Column(Integer, nullable=False, default=0, server_default="0")

    office_id = Column(UUID(as_uuid=True), ForeignKey("offices.id", ondelete="CASCADE"), nullable=True)

    permission = relationship("Permission", back_populates="user", passive_deletes=True)
    office = relationship("Office", back_populates="user", uselist=True)

    # jina la mtumiaji na simu ni vya kipekee ndani ya kampuni (kampuni mbili zinaweza kuwa na "admin")
    __table_args__ = (Index("ux_users_username", "company_id", "username", unique=True), Index("ux_users_phonenumber", "company_id", "phoneNumber", unique=True))
