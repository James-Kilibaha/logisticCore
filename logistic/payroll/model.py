"""Mishahara: wafanyakazi, viwango (PAYE, NSSF, SDL, WCF) na mishahara ya kila mwezi."""
from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from ..core.base_model import AuditedEntity, EntityBase


class Employee(AuditedEntity):
    __tablename__ = "employees"

    name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    position = Column(String, nullable=True)
    office_id = Column(UUID(as_uuid=True), ForeignKey("offices.id", ondelete="SET NULL"), nullable=True)
    basic = Column(Float, nullable=False, default=0.0)          # mshahara wa msingi (TSh kwa mwezi)
    allowance = Column(Float, nullable=False, default=0.0)      # posho zinazotozwa kodi
    deduction = Column(Float, nullable=False, default=0.0)      # makato mengine (mkopo, mchango ...)
    nssf = Column(Boolean, nullable=False, default=True)        # anachangia NSSF
    paye = Column(Boolean, nullable=False, default=True)        # anakatwa PAYE
    tin = Column(String, nullable=True)
    nssfNo = Column(String, nullable=True)
    bank = Column(String, nullable=True)                        # benki / namba ya simu ya kulipwa
    active = Column(Boolean, nullable=False, default=True)


class PayrollSettings(EntityBase):
    """Viwango (asilimia). Thibitisha na TRA / NSSF kila mwaka wa fedha - vinaweza kubadilishwa hapa."""
    __tablename__ = "payroll_settings"

    nssfEmployee = Column(Float, nullable=False, default=10.0)
    nssfEmployer = Column(Float, nullable=False, default=10.0)
    sdl = Column(Float, nullable=False, default=3.5)            # Skills Development Levy (mwajiri)
    sdlEnabled = Column(Boolean, nullable=False, default=False) # kwa waajiri wenye wafanyakazi 10+
    wcf = Column(Float, nullable=False, default=0.5)            # Workers Compensation Fund (mwajiri)
    # bendi za PAYE (Tanzania bara, kwa mwezi): JSON [[kuanzia, mpaka|null, kiasi_kisichobadilika, asilimia], ...]
    payeBands = Column(Text, nullable=False, default="")


class PayrollRun(AuditedEntity):
    __tablename__ = "payroll_runs"

    month = Column(String, nullable=False)                      # YYYY-MM (moja kwa kila kampuni)
    status = Column(String, nullable=False, default="DRAFT")    # DRAFT | POSTED
    institute_id = Column(UUID(as_uuid=True), ForeignKey("institutes.id", ondelete="SET NULL"), nullable=True)
    postedBy = Column(UUID(as_uuid=True), nullable=True)
    salaryExpense_id = Column(UUID(as_uuid=True), nullable=True)   # matumizi ya mishahara (gross)
    employerExpense_id = Column(UUID(as_uuid=True), nullable=True) # michango ya mwajiri
    note = Column(String, nullable=True)

    __table_args__ = (Index("ux_payroll_runs_month", "company_id", "month", unique=True),)


class PayrollLine(EntityBase):
    __tablename__ = "payroll_lines"

    run_id = Column(UUID(as_uuid=True), ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    name = Column(String, nullable=False)
    position = Column(String, nullable=True)
    office_id = Column(UUID(as_uuid=True), nullable=True)
    basic = Column(Float, nullable=False, default=0.0)
    allowance = Column(Float, nullable=False, default=0.0)
    gross = Column(Float, nullable=False, default=0.0)
    nssfEmployee = Column(Float, nullable=False, default=0.0)
    taxable = Column(Float, nullable=False, default=0.0)
    paye = Column(Float, nullable=False, default=0.0)
    deduction = Column(Float, nullable=False, default=0.0)
    net = Column(Float, nullable=False, default=0.0)
    nssfEmployer = Column(Float, nullable=False, default=0.0)
    sdl = Column(Float, nullable=False, default=0.0)
    wcf = Column(Float, nullable=False, default=0.0)

    __table_args__ = (Index("ix_payroll_lines_run", "run_id"),)
