"""
Madai ya gharama (v2.16).

Kazi inayohitaji gharama zake ziandikwe (mf. box limesafirishwa -> nauli; box limefika -> clearing/usafiri)
inaunda `CostDemand`. Saa ya kufunga kazi (`remindHour`) mhusika anakumbushwa (pop-up + 🔔). Siku inayofuata
(baada ya `graceDays`) kama bado halijajazwa, kazi zinazuiwa (kwa wote au kwa mhusika tu - `blockScope`)
mpaka gharama zijazwe, mhusika aseme "hakuna gharama", au mhasibu/msimamizi asamehe.
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from ..core.base_model import AuditedEntity, EntityBase

TRIGGERS = ("BOX_CLOSED", "BOX_ARRIVED")
OPEN, DONE, NONE, WAIVED = "OPEN", "DONE", "NONE", "WAIVED"


class DemandRule(EntityBase):
    __tablename__ = "demand_rules"

    trigger = Column(String, nullable=False)                    # BOX_CLOSED | BOX_ARRIVED (moja kwa kila kampuni)
    enabled = Column(Boolean, nullable=False, default=True)
    categories = Column(String, nullable=False, default="")     # "FREIGHT,CUSTOMS" ; "" = gharama yoyote
    responsible = Column(String, nullable=False, default="DOER")  # DOER (aliyefanya kazi) | ROLE
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    remindHour = Column(Integer, nullable=False, default=17)    # saa ya kufunga kazi (kukumbusha)
    graceDays = Column(Integer, nullable=False, default=0)      # 0 = kuzuia kuanzia kesho asubuhi
    blockScope = Column(String, nullable=False, default="EVERYONE")  # EVERYONE | RESPONSIBLE | NONE

    __table_args__ = (Index("ux_demand_rules_trigger", "company_id", "trigger", unique=True),)


class CostDemand(AuditedEntity):
    __tablename__ = "cost_demands"

    trigger = Column(String, nullable=False)
    package_id = Column(UUID(as_uuid=True), ForeignKey("packages.id", ondelete="CASCADE"), nullable=False)
    categories = Column(String, nullable=False, default="")
    doer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    responsible = Column(String, nullable=False, default="DOER")
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    blockScope = Column(String, nullable=False, default="EVERYONE")
    remindAt = Column(DateTime, nullable=False)
    blockAt = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default=OPEN)       # OPEN | DONE | NONE | WAIVED
    closedBy = Column(UUID(as_uuid=True), nullable=True)
    closedAt = Column(DateTime, nullable=True)
    note = Column(String, nullable=True)
    remindedAt = Column(DateTime, nullable=True)
    blockNotifiedAt = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_cost_demands_status", "status", "blockAt"),
                      Index("ix_cost_demands_package", "package_id", "trigger"))
