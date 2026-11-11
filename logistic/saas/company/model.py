from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from ...core.base_model import PlatformEntity


class Company(PlatformEntity):
    """
    Kampuni ya usafirishaji (mteja wako / tenant). Data yake yote (wateja, ankara, mabox ...) ina `company_id` yake.

    - `slug`   : jina fupi la kipekee (mf. "ymg") - linatumika kwenye subdomain (ymg.<PLATFORM_DOMAIN>)
                 na kwenye app ya simu (code ya kampuni).
    - `domain` : domain yake yenyewe (mf. "ymg.co.tz") - si lazima.
    - `settings`: mipangilio ya biashara (SMS, WhatsApp, stoo, ETA ...) - tazama company/settings.py.
    """
    __tablename__ = "companies"

    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    legalName = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)          # namba za mawasiliano (zinaonyeshwa kwa wateja wao)
    address = Column(String, nullable=True)
    country = Column(String, nullable=True, default="Tanzania")
    tin = Column(String, nullable=True)

    logoPath = Column(String, nullable=True)
    primaryColor = Column(String, nullable=True)   # "#1F4FD8"
    accentColor = Column(String, nullable=True)
    domain = Column(String, nullable=True)

    # PENDING (imejisajili - inasubiri uithibitishe) | ACTIVE | SUSPENDED (umeizuia) | REJECTED (umeikataa)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    ownerName = Column(String, nullable=True)
    ownerPhone = Column(String, nullable=True)
    notes = Column(Text, nullable=True)            # maelezo yako ya ndani (hayaonekani kwa kampuni)
    source = Column(String, nullable=True)         # SIGNUP | ADMIN
    signupPlanId = Column(String, nullable=True)   # mpango ulioombwa wakati wa kujisajili (majaribio yanaanza ukithibitisha)
    approvedBy = Column(String, nullable=True)
    approvedAt = Column(DateTime, nullable=True)
    settings = Column(JSONB, nullable=False, default=dict, server_default="{}")

    # Nafasi za ziada ulizoipa kampuni hii juu ya mipaka ya mpango wake (0 = kama mpango tu)
    extraUsers = Column(Integer, nullable=False, default=0, server_default="0")
    extraOffices = Column(Integer, nullable=False, default=0, server_default="0")
    extraInvoicesPerMonth = Column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        Index("ux_companies_slug", "slug", unique=True),
        Index("ux_companies_domain", "domain", unique=True),
    )
