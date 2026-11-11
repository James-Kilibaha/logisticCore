"""Endpoints za umma za SaaS: branding (kabla ya kuingia), mipango, na kampuni kujisajili yenyewe."""
from sqlalchemy.orm import Session

from ... import config
from ...core import ratelimit, tenant
from ...core.exceptions import BadRequest, NotFound
from ..company import schema as company_schema, service as company_service
from ..company.dao import CompanyDao
from ..company.model import Company


def current_company(db: Session) -> Company | None:
    cid = tenant.company_id()
    return CompanyDao(db).get(cid) if cid else None


def branding(db: Session) -> dict:
    return company_service.branding(current_company(db))


def logo_path(db: Session):
    from ...core import files

    company = current_company(db)
    if company is None or not company.logoPath:
        raise NotFound("Logo haipo")
    return files.existing(company.logoPath)


def signup(db: Session, data: company_schema.Signup, ip: str | None) -> dict:
    if not config.SELF_SIGNUP_ENABLED:
        raise BadRequest("Usajili wa moja kwa moja umezimwa - wasiliana na mtoa huduma")
    ratelimit.hit(f"signup:{ip or '-'}", limit=5, window_seconds=3600)
    company = company_service.create(db, data, source="SIGNUP")
    info = company_service.branding(company)
    pending = company.status == "PENDING"
    message = (f"Ombi la akaunti ya {company.name} limepokelewa - linasubiri kuthibitishwa na mtoa huduma. "
               f"Utapata SMS likikubaliwa. Code ya kampuni: {company.slug}") if pending else \
              (f"Akaunti ya {company.name} imefunguliwa - majaribio ya siku {config.TRIAL_DAYS}. "
               f"Code ya kampuni: {company.slug}")
    return {"company": info, "username": data.admin.username.strip(), "pending": pending, "message": message}
