"""
Kampuni (tenants): kusajili, kuandaa (provision), wasifu (jina, logo, rangi), mipangilio na kuzuia.
"""
import logging
import re
import uuid

from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.orm import Session

from ... import config
from ...core import files, tenant
from ...core.base_model import utc_now
from ...core.exceptions import BadRequest, Conflict, NotFound
from ...db import Base, SessionLocal, engine
from . import schema, settings as company_settings
from .dao import CompanyDao
from .model import Company

logger = logging.getLogger(__name__)

RESERVED_SLUGS = {"www", "api", "app", "admin", "platform", "mail", "smtp", "ftp", "static", "cdn", "help",
                  "support", "docs", "status", "login", "signup", "billing", "dev", "test", "staging"}
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,28})[a-z0-9]$")
LOGO_EXT = {".png", ".jpg", ".jpeg"}
LOGO_MAX_BYTES = 1_000_000


def clean_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", (value or "").strip().lower()).strip("-")
    if not _SLUG.match(slug):
        raise BadRequest("Code ya kampuni: herufi ndogo, namba na '-' tu (herufi 3 hadi 30) / invalid company code")
    if slug in RESERVED_SLUGS:
        raise BadRequest("Code hii ya kampuni haiwezi kutumika / this company code is reserved")
    return slug


def clean_domain(value: str | None) -> str | None:
    domain = (value or "").strip().lower()
    if not domain:
        return None
    domain = re.sub(r"^https?://", "", domain).split("/")[0].split(":")[0].strip(".")
    if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", domain):
        raise BadRequest("Domain si sahihi (mfano: ymg.co.tz)")
    if config.PLATFORM_DOMAIN and (domain == config.PLATFORM_DOMAIN.lower()):
        raise BadRequest("Domain hii ni ya mfumo wenyewe")
    return domain


def get(db: Session, company_id) -> Company:
    company = CompanyDao(db).get(company_id)
    if company is None:
        raise NotFound("Kampuni haipo")
    return company


def _check_unique(db: Session, slug: str, domain: str | None, except_id=None) -> None:
    dao = CompanyDao(db)
    other = dao.by_slug(slug)
    if other is not None and other.id != except_id:
        raise Conflict("Code hii ya kampuni imeshachukuliwa / company code already taken")
    if domain:
        other = dao.by_domain(domain)
        if other is not None and other.id != except_id:
            raise Conflict("Domain hii inatumiwa na kampuni nyingine")


def slug_available(db: Session, value: str) -> dict:
    try:
        slug = clean_slug(value)
    except BadRequest as error:
        return {"slug": value, "available": False, "reason": error.detail}
    taken = CompanyDao(db).by_slug(slug) is not None
    return {"slug": slug, "available": not taken, "reason": "Imeshachukuliwa / taken" if taken else None}


# ------------------------------------------------------------------ kusajili

def provision(cid, admin: schema.CompanyAdmin) -> None:
    """Data ya kuanzia ya kampuni mpya: aina za SMS, roles, na msimamizi wake wa kwanza."""
    from ...role.service import ensure_defaults_roles
    from ...settings.sms_set.service import create_missing as sms_kinds
    from ...user import service as user_service
    from ...user.schema import UserCreate

    with tenant.use_company(cid):
        db = SessionLocal()
        try:
            sms_kinds(db)
            ensure_defaults_roles(db)
            _rule_defaults(db)
            user_service.create(db, UserCreate(firstName=admin.firstName, lastName=admin.lastName,
                                               phoneNumber=admin.phoneNumber, username=admin.username.strip(),
                                               password=admin.password), grant_all=True)
            _finance_defaults(db)
        finally:
            db.close()


def _rule_defaults(db) -> None:
    """Sheria za kuanzia za kampuni: taarifa za pop-up na SMS za moja kwa moja (kila kampuni ina zake)."""
    from ...popup.service import ensure_defaults as popup_defaults
    from ...sms.reminders import ensure_defaults as auto_sms_defaults

    popup_defaults(db)
    auto_sms_defaults(db)


def _finance_defaults(db) -> None:
    """Uhasibu: makundi ya kuanzia ya matumizi/mapato + sheria za madai ya gharama (baada ya mtumiaji wa kwanza)."""
    from ...accounting.service import ensure_defaults as accounting_defaults
    from ...demand.service import ensure_rules as demand_rules

    accounting_defaults(db)
    demand_rules(db)


def seed_existing() -> None:
    """Server ikianza: kila kampuni inapata aina mpya za SMS, roles na ruhusa za moduli mpya."""
    from ...permission import service as permission_service
    from ...role.service import ensure_defaults_roles
    from ...settings.sms_set.service import create_missing as sms_kinds

    for cid, slug in tenant.active_company_ids():
        try:
            with tenant.use_company(cid, slug):
                db = SessionLocal()
                try:
                    ensure_defaults_roles(db)  # kwanza role (moduli mpya), kisha watumiaji wanafuata role zao
                    permission_service.ensure_defaults_for_all_users(db)
                    sms_kinds(db)
                    _rule_defaults(db)
                    _finance_defaults(db)
                finally:
                    db.close()
        except Exception:
            logger.exception("Seed failed for company %s", slug)


def create(db: Session, data: schema.CompanyCreate | schema.Signup, source: str, by: str | None = None) -> Company:
    from ...core.phone import try_normalize
    from ...core.security import password_problem
    from ..plan.dao import PlanDao
    from ..plan.model import Plan
    from ..subscription import service as subscriptions

    is_signup = isinstance(data, schema.Signup)
    name = (data.companyName if is_signup else data.name).strip()
    slug = clean_slug(data.slug)
    domain = None if is_signup else clean_domain(data.domain)
    _check_unique(db, slug, domain)
    problem = password_problem(data.admin.password)
    if problem:
        raise BadRequest(problem)

    plan = db.get(Plan, data.plan_id) if data.plan_id else PlanDao(db).cheapest_public()
    if plan is None or (is_signup and not (plan.isActive and plan.isPublic)):
        raise BadRequest("Chagua mpango sahihi / choose a valid plan")

    phone = data.phone
    pending = is_signup and config.SIGNUP_REQUIRES_APPROVAL
    company = Company(
        name=name, slug=slug, domain=domain, phone=phone, email=(data.email or None),
        country=data.country or "Tanzania", source=source, status="PENDING" if pending else "ACTIVE", settings={},
        signupPlanId=str(plan.id) if is_signup else None,
        ownerName=f"{data.admin.firstName} {data.admin.lastName}".strip() if is_signup else data.ownerName,
        ownerPhone=try_normalize(phone if is_signup else (data.ownerPhone or data.admin.phoneNumber)),
    )
    if not is_signup:
        company.address, company.tin, company.notes = data.address, data.tin, data.notes
        company.primaryColor, company.accentColor = data.primaryColor, data.accentColor
    db.add(company)
    db.commit()
    db.refresh(company)
    try:
        provision(company.id, data.admin)
    except Exception:
        db.delete(company)
        db.commit()
        raise
    if pending:
        # majaribio yanaanza ukiithibitisha (approve) - siku hazipotei ikisubiri
        logger.info("Kampuni mpya inasubiri kuthibitishwa: %s (%s)", company.name, company.slug)
        _alert_platform(f"{config.PLATFORM_NAME}: kampuni mpya imejisajili - {company.name} ({company.slug}), "
                        f"simu {company.phone or '-'}. Ithibitishe kwenye admin panel.")
        from ..notice.service import notify

        notify("SIGNUP", "COMPANIES", f"Kampuni mpya inasubiri kuidhinishwa: {company.name}",
               f"{company.slug} · {company.ownerName or '-'} · simu {company.phone or '-'}",
               link=f"company:{company.id}", company_id=company.id, urgent=True)
        return company
    trial = config.TRIAL_DAYS if is_signup or data.trialDays is None else data.trialDays
    if trial > 0:
        subscriptions.start_trial(db, company.id, plan, days=trial, by=by or "signup")
    if not is_signup:
        company.approvedBy, company.approvedAt = by, company.created_at
        db.commit()
    logger.info("Kampuni mpya: %s (%s) - %s", company.name, company.slug, source)
    return company


def _sms(phone: str | None, text: str) -> None:
    """SMS kupitia akaunti yako ya SMS (.env) - haizuii kazi ikishindwa."""
    from ...core.phone import try_normalize
    from ...sms.model import Sms
    from ...sms.service import _send_to_gateway

    number = try_normalize(phone)
    if not number or not (config.SMS_CLIENT_ID and config.SMS_CLIENT_SECRET):
        return
    try:
        _send_to_gateway(Sms(text=text[:450], msisdn=number, source=config.PLATFORM_SMS_SOURCE or config.SMS_SOURCE_NAME,
                             reference=f"PLT{uuid.uuid4().hex[:17].upper()}", coding=config.SMS_CODING,
                             smsFor="CUSTOM"))
    except Exception:
        logger.exception("Platform SMS failed")


def _alert_platform(text: str) -> None:
    """Taarifa kwako (PLATFORM_SUPPORT_PHONE / ALERT_PHONES) kampuni mpya ikijisajili."""
    phones = [p for p in [config.PLATFORM_SUPPORT_PHONE, *config.ALERT_PHONES] if p]
    for phone in dict.fromkeys(phones):
        tenant.spawn(_sms, phone, text)


def approve(db: Session, company_id, data: schema.Approve, by: str) -> Company:
    """Kuthibitisha kampuni iliyojisajili: inafunguliwa na majaribio yanaanza leo."""
    from ..plan.model import Plan
    from ..plan.dao import PlanDao
    from ..subscription import service as subscriptions
    from ..subscription.dao import SubscriptionDao

    company = get(db, company_id)
    if company.status not in ("PENDING", "REJECTED"):
        raise BadRequest(f"Kampuni hii haisubiri kuthibitishwa ({company.status})")
    plan_id = data.plan_id or company.signupPlanId
    plan = db.get(Plan, uuid.UUID(str(plan_id))) if plan_id else PlanDao(db).cheapest_public()
    if plan is None:
        raise BadRequest("Chagua mpango")
    company.status = "ACTIVE"
    company.approvedBy, company.approvedAt = by, utc_now()
    if data.note:
        company.notes = ((company.notes or "") + f"\n[IMETHIBITISHWA] {data.note}").strip()
    db.commit()
    trial = config.TRIAL_DAYS if data.trialDays is None else data.trialDays
    if trial > 0 and SubscriptionDao(db).latest(company.id) is None:
        subscriptions.start_trial(db, company.id, plan, days=trial, by=by)
    db.refresh(company)
    _changed(company)
    from . import settings as company_settings

    url = company_settings.app_url(company)
    tenant.spawn(_sms, company.ownerPhone or company.phone,
                 f"{config.PLATFORM_NAME}: akaunti ya {company.name} imethibitishwa. Code ya kampuni: {company.slug}."
                 + (f" Ingia: {url}" if url else "") + (f" Majaribio: siku {trial}." if trial > 0 else ""))
    logger.info("Kampuni imethibitishwa: %s (%s) na %s", company.name, company.slug, by)
    return company


def reject(db: Session, company_id, data: schema.Reject, by: str) -> Company:
    company = get(db, company_id)
    if company.status != "PENDING":
        raise BadRequest(f"Kampuni hii haisubiri kuthibitishwa ({company.status})")
    company.status = "REJECTED"
    company.notes = ((company.notes or "") + f"\n[IMEKATALIWA na {by}] {data.reason or ''}").strip()
    db.commit()
    db.refresh(company)
    _changed(company)
    tenant.spawn(_sms, company.ownerPhone or company.phone,
                 f"{config.PLATFORM_NAME}: ombi la akaunti ya {company.name} halikukubaliwa."
                 + (f" Sababu: {data.reason}" if data.reason else "")
                 + (f" Msaada: {config.PLATFORM_SUPPORT_PHONE}" if config.PLATFORM_SUPPORT_PHONE else ""))
    return company


def update(db: Session, data: schema.CompanyUpdate) -> Company:
    company = get(db, data.id)
    slug = clean_slug(data.slug)
    domain = clean_domain(data.domain)
    _check_unique(db, slug, domain, except_id=company.id)
    for field in ("name", "legalName", "phone", "email", "address", "country", "tin", "primaryColor",
                  "accentColor", "ownerName", "ownerPhone", "notes"):
        setattr(company, field, getattr(data, field))
    company.name = data.name.strip()
    company.slug, company.domain = slug, domain
    db.commit()
    db.refresh(company)
    _changed(company)
    return company


def set_status(db: Session, data: schema.StatusUpdate) -> Company:
    status = data.status.strip().upper()
    if status not in ("ACTIVE", "SUSPENDED"):
        raise BadRequest("status: ACTIVE au SUSPENDED")
    company = get(db, data.id)
    company.status = status
    if data.reason:
        company.notes = ((company.notes or "") + f"\n[{status}] {data.reason}").strip()
    db.commit()
    db.refresh(company)
    _changed(company)
    return company


def set_limits(db: Session, company_id, data: schema.LimitsUpdate) -> Company:
    """Super admin anaipa kampuni nafasi za ziada (watumiaji, ofisi, ankara) juu ya mpango wake."""
    from ..subscription import service as subscriptions

    company = get(db, company_id)
    company.extraUsers = data.extraUsers
    company.extraOffices = data.extraOffices
    company.extraInvoicesPerMonth = data.extraInvoicesPerMonth
    db.commit()
    db.refresh(company)
    subscriptions.invalidate(company.id)
    return company


def delete(db: Session, company_id, confirm_slug: str) -> dict:
    """Inafuta kampuni NA DATA YAKE YOTE (haiwezi kurudishwa). Lazima uandike slug yake kuthibitisha."""
    company = get(db, company_id)
    if (confirm_slug or "").strip().lower() != company.slug:
        raise BadRequest("Andika code ya kampuni kuthibitisha kufuta")
    slug, cid = company.slug, company.id
    db.delete(company)
    db.commit()
    _changed(company)
    import shutil

    try:
        shutil.rmtree(files.absolute(str(cid)), ignore_errors=True)
    except Exception:
        logger.exception("Mafaili ya kampuni %s hayakufutwa", slug)
    logger.warning("Kampuni imefutwa: %s", slug)
    return {"deleted": True, "slug": slug}


def _changed(company: Company) -> None:
    from ..middleware import forget

    company_settings.invalidate(company.id)
    forget(company)


# ------------------------------------------------------------------ kampuni yenyewe

def current(db: Session) -> Company:
    return get(db, tenant.require_company_id())


def update_profile(db: Session, data: schema.ProfileUpdate) -> Company:
    company = current(db)
    for field in ("legalName", "phone", "email", "address", "country", "tin", "primaryColor", "accentColor"):
        setattr(company, field, getattr(data, field))
    company.name = data.name.strip()
    db.commit()
    db.refresh(company)
    _changed(company)
    return company


def update_settings(db: Session, data: schema.SettingsUpdate) -> dict:
    company = current(db)
    values = dict(company.settings or {})
    for name, raw in (data.values or {}).items():
        if name not in company_settings.EDITABLE:
            raise BadRequest(f"Mpangilio '{name}' haujulikani")
        if name in company_settings.SECRETS and isinstance(raw, str) and raw.startswith("••"):
            continue  # siri haijabadilishwa
        try:
            value = company_settings.coerce(name, raw)
        except (TypeError, ValueError):
            raise BadRequest(f"Thamani ya {name} si sahihi")
        if value is None:
            values.pop(name, None)
        else:
            values[name] = value
    if values.get("TIMEZONE"):
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(values["TIMEZONE"])
        except Exception:
            raise BadRequest("TIMEZONE si sahihi (mfano Africa/Dar_es_Salaam)")
    company.settings = values
    db.commit()
    db.refresh(company)
    _changed(company)
    return company_settings.public_view(company)


def logo_dir(cid) -> str:
    return f"{cid}/Branding"


def save_logo(db: Session, filename: str, content: bytes, company: Company | None = None) -> Company:
    import os

    company = company or current(db)
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in LOGO_EXT:
        raise BadRequest("Logo: PNG au JPG tu")
    if len(content) > LOGO_MAX_BYTES:
        raise BadRequest("Logo ni kubwa mno (mwisho 1MB)")
    directory = logo_dir(company.id)
    files.ensure_dir(directory)
    relative = f"{directory}/logo_{uuid.uuid4().hex[:8]}{ext}"
    files.absolute(relative).write_bytes(content)
    old = company.logoPath
    company.logoPath = relative
    db.commit()
    db.refresh(company)
    if old and old != relative:
        try:
            files.remove(old)
        except OSError:
            pass
    _changed(company)
    return company


def remove_logo(db: Session, company: Company | None = None) -> Company:
    company = company or current(db)
    if company.logoPath:
        try:
            files.remove(company.logoPath)
        except OSError:
            pass
    company.logoPath = None
    db.commit()
    db.refresh(company)
    _changed(company)
    return company


def branding(company: Company | None) -> dict:
    """Taarifa za umma za kampuni (jina, logo, rangi) - app inazitumia kabla ya kuingia."""
    base = {"platform": {"name": config.PLATFORM_NAME, "domain": config.PLATFORM_DOMAIN or None,
                         "supportPhone": config.PLATFORM_SUPPORT_PHONE or None,
                         "supportEmail": config.PLATFORM_SUPPORT_EMAIL or None,
                         "signup": config.SELF_SIGNUP_ENABLED}}
    if company is None:
        return {"resolved": False, **base}
    with tenant.use_company(company.id, company.slug):
        tracking, origin = config.PUBLIC_TRACKING, config.COMPANY_ORIGIN
    version = (company.logoPath or "").rsplit("_", 1)[-1].split(".")[0] if company.logoPath else None
    return {
        "resolved": True,
        "id": str(company.id),
        "slug": company.slug,
        "name": company.name,
        "phone": company.phone,
        "email": company.email,
        "origin": origin,
        "logoUrl": f"/api/public/branding/logo?company={company.slug}&v={version}" if company.logoPath else None,
        "primaryColor": company.primaryColor,
        "accentColor": company.accentColor,
        "domain": company.domain,
        "appUrl": company_settings.app_url(company) or None,
        "tracking": bool(tracking),
        "active": company.status == "ACTIVE",
        "status": company.status,
        **base,
    }


def profile(db: Session) -> dict:
    """Ukurasa wa "Kampuni yangu": wasifu, mipangilio, subscription, matumizi."""
    from ..subscription import service as subscriptions

    company = current(db)
    return {
        "company": schema.CompanyOut.model_validate(company).model_dump(mode="json"),
        "branding": branding(company),
        "settings": company_settings.public_view(company),
        "subscription": subscriptions.state(company.id),
        "usage": subscriptions.usage(db, company.id),
        "payTo": config.PLATFORM_PAYMENT_INFO or None,
    }


# ------------------------------------------------------------------ data ya mfumo wa zamani

def adopt_orphans() -> None:
    """
    Database ya mfumo wa zamani (TransportCore): rekodi zisizo na company_id zinapewa kampuni DEFAULT_COMPANY_SLUG.
    Inafanya kazi tu kama DEFAULT_COMPANY_SLUG imewekwa na kampuni hiyo ipo.
    """
    if not config.DEFAULT_COMPANY_SLUG:
        return
    with tenant.system():
        db = SessionLocal()
        try:
            company = CompanyDao(db).by_slug(config.DEFAULT_COMPANY_SLUG)
        finally:
            db.close()
    if company is None:
        logger.warning("DEFAULT_COMPANY_SLUG=%s: kampuni haipo bado", config.DEFAULT_COMPANY_SLUG)
        return
    existing = set(sa_inspect(engine).get_table_names())
    moved = 0
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing or "company_id" not in table.c or table.name in (
                    "subscriptions", "subscription_payments"):
                continue
            result = conn.execute(text(f'UPDATE "{table.name}" SET company_id = :cid WHERE company_id IS NULL'),
                                  {"cid": company.id})
            moved += result.rowcount or 0
    if moved:
        logger.info("Rekodi %s za zamani zimepewa kampuni %s", moved, company.slug)
