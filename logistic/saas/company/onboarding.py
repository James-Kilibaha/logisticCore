"""
Hatua za kwanza za kampuni mpya - zinahesabiwa kutoka data yenyewe (hakuna kuweka alama kwa mkono).
Dashboard inaonyesha orodha hii mpaka zote zikamilike (au mtumiaji aifiche).
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from ... import config


def steps(db: Session, company) -> dict:
    cid = company.id
    s = company.settings or {}

    def count(table: str, where: str = "") -> int:
        sql = f'SELECT COUNT(*) FROM "{table}" WHERE company_id = :cid {where}'
        return int(db.execute(text(sql), {"cid": cid}).scalar() or 0)

    sms_ready = bool(s.get("SMS_CLIENT_ID") and s.get("SMS_CLIENT_SECRET")) or bool(
        config.PLATFORM_SMS_FOR_TENANTS and config.SMS_CLIENT_ID)
    items = [
        ("LOGO", bool(company.logoPath), "company"),
        ("OFFICE", count("offices") > 0, "settings"),
        ("PRICE", count("prices") > 0, "settings"),
        ("ACCOUNT", count("institutes") > 0, "settings"),
        ("USERS", count("users") > 1, "users"),
        ("SMS", sms_ready, "settings"),
        ("CUSTOMER", count("customers") > 0, "customers"),
        ("INVOICE", count("invoices") > 0, "invoices"),
        ("WHATSAPP", bool(s.get("WHATSAPP_PHONE_NUMBER_ID") and s.get("WHATSAPP_TOKEN")), "whatsapp"),
        ("MOBILE_PAY", bool(s.get("AZAMPAY_CLIENT_ID") and s.get("AZAMPAY_CLIENT_SECRET")), "mobilePay"),
    ]
    out = [{"key": k, "done": done, "target": target, "optional": k in ("WHATSAPP", "MOBILE_PAY")}
           for k, done, target in items]
    required = [x for x in out if not x["optional"]]
    done = sum(1 for x in required if x["done"])
    return {"steps": out, "done": done, "total": len(required), "complete": done == len(required),
            "hidden": bool(s.get("_ONBOARDING_HIDDEN"))}


def hide(db: Session, company, hidden: bool = True) -> dict:
    from sqlalchemy.orm.attributes import flag_modified

    from ...core import tenant
    from . import settings as company_settings

    with tenant.system():
        company = db.merge(company)
        company.settings = {**(company.settings or {}), "_ONBOARDING_HIDDEN": bool(hidden)}
        flag_modified(company, "settings")
        db.commit()
    company_settings.invalidate(company.id)
    return steps(db, company)
