"""
Mipango ya subscription. Moduli za ziada (OPTIONAL_MODULES) zinaweza kuwashwa/kuzimwa kwa kila mpango;
moduli za msingi (ankara, wateja, mabox, stoo, malipo ...) ziko kwenye kila mpango.
"""
import re

from sqlalchemy.orm import Session

from ...core.enums import Module
from ...core.exceptions import BadRequest, Conflict, NotFound
from . import schema
from .dao import PlanDao
from .model import Plan

# Moduli zinazoweza kuuzwa kwa mipango ya juu
OPTIONAL_MODULES = [Module.WHATSAPP.value, Module.BROADCAST.value, Module.QUOTE.value, Module.CLAIM.value,
                    Module.CASHUP.value, Module.PROFIT.value, Module.IMPORT.value, Module.AUDIT.value,
                    Module.ACCOUNTING.value, Module.PAYROLL.value]

# Mipango ya kuanzia (inaundwa mara ya kwanza tu kama hakuna mpango wowote - unaweza kuibadilisha)
DEFAULT_PLANS = [
    dict(code="starter", name="Starter", description="Kampuni ndogo: ofisi 1, watumiaji 3", price=50000,
         months=1, maxUsers=3, maxOffices=1, maxInvoicesPerMonth=300, modules=[], sortOrder=1),
    dict(code="business", name="Business", description="Ofisi 3, watumiaji 10, WhatsApp, makadirio, faida",
         price=120000, months=1, maxUsers=10, maxOffices=3, maxInvoicesPerMonth=2000,
         modules=[Module.WHATSAPP.value, Module.BROADCAST.value, Module.QUOTE.value, Module.CASHUP.value,
                  Module.PROFIT.value, Module.IMPORT.value, Module.ACCOUNTING.value], sortOrder=2),
    dict(code="enterprise", name="Enterprise", description="Bila kikomo - moduli zote", price=250000, months=1,
         maxUsers=None, maxOffices=None, maxInvoicesPerMonth=None, modules=None, sortOrder=3),
]


def _clean_modules(modules: list[str] | None) -> list[str] | None:
    if modules is None:
        return None
    out = []
    for m in modules:
        m = (m or "").strip().upper()
        if m not in OPTIONAL_MODULES:
            raise BadRequest(f"Moduli '{m}' haijulikani. Zinazoruhusiwa: {', '.join(OPTIONAL_MODULES)}")
        if m not in out:
            out.append(m)
    return out


def _code(value: str) -> str:
    code = re.sub(r"[^a-z0-9-]+", "-", (value or "").strip().lower()).strip("-")
    if len(code) < 2:
        raise BadRequest("Code ya mpango si sahihi")
    return code


def seed_defaults(db: Session) -> None:
    dao = PlanDao(db)
    if dao.query().first() is not None:
        return
    for row in DEFAULT_PLANS:
        db.add(Plan(currency="TZS", isPublic=True, isActive=True, **row))
    db.commit()


def list_all(db: Session, public_only: bool = False) -> list[Plan]:
    return PlanDao(db).ordered(public_only=public_only)


def get(db: Session, plan_id) -> Plan:
    plan = PlanDao(db).get(plan_id)
    if plan is None:
        raise NotFound("Mpango haupo")
    return plan


def create(db: Session, data: schema.PlanCreate) -> Plan:
    dao = PlanDao(db)
    code = _code(data.code)
    if dao.by_code(code):
        raise Conflict("Code hii ya mpango ipo tayari")
    values = data.model_dump()
    values.update(code=code, currency=data.currency.strip().upper() or "TZS", modules=_clean_modules(data.modules))
    return dao.create(**values)


def update(db: Session, data: schema.PlanUpdate) -> Plan:
    dao = PlanDao(db)
    plan = get(db, data.id)
    code = _code(data.code)
    other = dao.by_code(code)
    if other is not None and other.id != plan.id:
        raise Conflict("Code hii ya mpango ipo tayari")
    values = data.model_dump(exclude={"id"})
    values.update(code=code, currency=data.currency.strip().upper() or "TZS", modules=_clean_modules(data.modules))
    plan = dao.update(plan, **values)
    from ..subscription import service as subscriptions

    subscriptions.invalidate()
    return plan


def delete(db: Session, plan_id) -> dict:
    from ..subscription.model import Subscription

    plan = get(db, plan_id)
    used = db.query(Subscription.id).filter(Subscription.plan_id == plan.id).first() is not None
    if used:
        PlanDao(db).update(plan, isActive=False, isPublic=False)
        return {"deleted": True, "archived": True}
    PlanDao(db).delete(plan)
    return {"deleted": True, "archived": False}
