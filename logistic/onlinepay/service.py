"""
Malipo ya simu kupitia AzamPay.

Mtiririko:
  1. Mtumiaji anaanzisha (subscription au ankara): tunatuma ombi kwa AzamPay -> mteja anapata ombi la PIN.
  2. Mteja anaweka PIN -> AzamPay inatuma callback kwenye URL yetu ya siri.
  3. Callback "success": malipo yanarekodiwa yenyewe (subscription inaongezwa / ankara inalipwa + risiti SMS).
  4. App inauliza hali (GET) kila sekunde chache hadi SUCCESS / FAILED / EXPIRED.

URL za callback (zina siri - usizichapishe):
  - Subscription (akaunti yako):  /api/public/payments/azampay/<token ya mfumo>
  - Ankara za kampuni:            /api/public/payments/azampay/<slug>/<token ya kampuni>
"""
import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from .. import config
from ..core import tenant
from ..core.base_model import utc_now
from ..core.exceptions import BadRequest, NotFound
from ..core.phone import normalize
from . import azampay
from .model import OnlinePayment

logger = logging.getLogger(__name__)

MASK = "••••••"
_SECRET_KEYS = ("AZAMPAY_CLIENT_SECRET", "AZAMPAY_API_KEY")
KEYS = ("AZAMPAY_ENV", "AZAMPAY_APP_NAME", "AZAMPAY_CLIENT_ID", "AZAMPAY_CLIENT_SECRET", "AZAMPAY_API_KEY",
        "AZAMPAY_INSTITUTE_ID", "AZAMPAY_ENABLED")


# ------------------------------------------------------------------ akaunti za AzamPay

def platform_client() -> azampay.Azampay:
    return azampay.Azampay(config.AZAMPAY_APP_NAME, config.AZAMPAY_CLIENT_ID, config.AZAMPAY_CLIENT_SECRET,
                           config.AZAMPAY_API_KEY, config.AZAMPAY_ENV, config.AZAMPAY_AUTH_URL or None,
                           config.AZAMPAY_BASE_URL or None)


def platform_enabled() -> bool:
    return bool(config.AZAMPAY_APP_NAME and config.AZAMPAY_CLIENT_ID and config.AZAMPAY_CLIENT_SECRET)


def _company(db: Session, company_id=None):
    from ..saas.company.model import Company

    cid = company_id or tenant.require_company_id()
    with tenant.system():
        company = db.get(Company, cid)
    if company is None:
        raise NotFound("Company not found")
    return company


def company_client(company) -> azampay.Azampay:
    s = company.settings or {}
    if not s.get("AZAMPAY_ENABLED", True):
        raise BadRequest("Malipo ya simu yamezimwa (Mipangilio -> Malipo ya simu)")
    return azampay.Azampay(s.get("AZAMPAY_APP_NAME", ""), s.get("AZAMPAY_CLIENT_ID", ""),
                           s.get("AZAMPAY_CLIENT_SECRET", ""), s.get("AZAMPAY_API_KEY", ""),
                           s.get("AZAMPAY_ENV", "sandbox"))


def _token(scope: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), f"azampay:{scope}".encode(), hashlib.sha256).hexdigest()[:32]


def _base_url(company=None) -> str:
    from ..saas.company import settings as company_settings

    base = (company_settings.app_url(company) if company is not None else "") or \
        (f"https://{config.PLATFORM_DOMAIN}" if config.PLATFORM_DOMAIN else "")
    return base.rstrip("/")


def platform_callback_url() -> str:
    return f"{_base_url()}/api/public/payments/azampay/{_token('platform')}"


def company_callback_url(company) -> str:
    return f"{_base_url(company)}/api/public/payments/azampay/{company.slug}/{_token(f'company:{company.id}')}"


def settings_view(db: Session) -> dict:
    company = _company(db)
    s = company.settings or {}
    return {
        "connected": bool(s.get("AZAMPAY_APP_NAME") and s.get("AZAMPAY_CLIENT_ID") and s.get("AZAMPAY_CLIENT_SECRET")),
        "enabled": bool(s.get("AZAMPAY_ENABLED", True)),
        "env": s.get("AZAMPAY_ENV", "sandbox"),
        "appName": s.get("AZAMPAY_APP_NAME", ""),
        "clientId": s.get("AZAMPAY_CLIENT_ID", ""),
        "clientSecret": MASK if s.get("AZAMPAY_CLIENT_SECRET") else "",
        "apiKey": MASK if s.get("AZAMPAY_API_KEY") else "",
        "instituteId": s.get("AZAMPAY_INSTITUTE_ID"),
        "callbackUrl": company_callback_url(company),
        "providers": list(azampay.PROVIDERS.values()),
    }


def settings_update(db: Session, data) -> dict:
    """Kuhifadhi akaunti ya AzamPay ya kampuni; inajaribu kupata token kwanza (taarifa sahihi)."""
    from sqlalchemy.orm.attributes import flag_modified

    from ..saas.company import settings as company_settings

    company = _company(db)
    s = dict(company.settings or {})
    new = {
        "AZAMPAY_ENV": "live" if (data.env or "").lower() == "live" else "sandbox",
        "AZAMPAY_APP_NAME": data.appName.strip(),
        "AZAMPAY_CLIENT_ID": data.clientId.strip(),
        "AZAMPAY_CLIENT_SECRET": s.get("AZAMPAY_CLIENT_SECRET", "") if data.clientSecret == MASK
        else data.clientSecret.strip(),
        "AZAMPAY_API_KEY": s.get("AZAMPAY_API_KEY", "") if data.apiKey == MASK else (data.apiKey or "").strip(),
        "AZAMPAY_ENABLED": bool(data.enabled),
    }
    if data.instituteId is not None:
        new["AZAMPAY_INSTITUTE_ID"] = str(data.instituteId) if data.instituteId else None
    azampay.Azampay(new["AZAMPAY_APP_NAME"], new["AZAMPAY_CLIENT_ID"], new["AZAMPAY_CLIENT_SECRET"],
                    new["AZAMPAY_API_KEY"], new["AZAMPAY_ENV"])._token(fresh=True)
    with tenant.system():
        company = db.merge(company)
        company.settings = {**s, **new}
        flag_modified(company, "settings")
        db.commit()
    company_settings.invalidate(company.id)
    return settings_view(db)


def settings_clear(db: Session) -> dict:
    from sqlalchemy.orm.attributes import flag_modified

    from ..saas.company import settings as company_settings

    company = _company(db)
    s = {k: v for k, v in (company.settings or {}).items() if k not in KEYS}
    with tenant.system():
        company = db.merge(company)
        company.settings = s
        flag_modified(company, "settings")
        db.commit()
    company_settings.invalidate(company.id)
    return settings_view(db)


# ------------------------------------------------------------------ kuanzisha malipo

def _external_id() -> str:
    return f"LG{utc_now():%y%m%d}{secrets.token_hex(8).upper()}"


def _start(db: Session, row: OnlinePayment, client: azampay.Azampay) -> OnlinePayment:
    with tenant.system():
        db.add(row)
        db.commit()
        try:
            row.gatewayRef = client.checkout(row.msisdn, row.amount, row.provider, row.externalId) or None
            row.message = "Ombi la PIN limetumwa kwenye simu ya mteja"
        except BadRequest as error:
            row.status = "FAILED"
            row.message = str(error.detail)[:300]
            row.completedAt = utc_now()
            db.commit()
            raise
        db.commit()
        db.refresh(row)
    return row


def start_subscription(db: Session, data, user) -> dict:
    """Kampuni inalipia subscription kwa simu (akaunti yako ya AzamPay)."""
    from ..saas.plan.model import Plan

    if not platform_enabled():
        raise BadRequest("Malipo ya simu ya subscription bado hayajawekwa na mtoa huduma - tumia njia nyingine")
    company = _company(db)
    with tenant.system():
        plan = db.get(Plan, data.plan_id)
    if plan is None or not plan.isActive:
        raise NotFound("Mpango haupo")
    if (plan.currency or "TZS").upper() != "TZS":
        raise BadRequest("Malipo ya simu ni kwa TZS tu - mpango huu una sarafu nyingine")
    from ..saas.coupon import service as coupons

    price = coupons.evaluate(db, getattr(data, "couponCode", None), company.id, plan, int(data.periods))
    amount = price["amount"]
    if amount < 100:
        raise BadRequest("Kiasi ni kidogo mno kwa malipo ya simu")
    msisdn = normalize(data.phone, required=True)
    row = OnlinePayment(purpose="SUBSCRIPTION", company_id=company.id, externalId=_external_id(),
                        provider=azampay.provider_name(data.provider), msisdn=msisdn, amount=amount, currency="TZS",
                        plan_id=plan.id, periods=int(data.periods), couponCode=price["code"],
                        startMode=(getattr(data, "startMode", None) or "QUEUE").upper()[:10],
                        discount=price["discount"] or None, user_id=getattr(user, "id", None),
                        username=getattr(user, "username", None))
    return out(_start(db, row, platform_client()))


def start_invoice(db: Session, data, user) -> dict:
    """Mteja analipia ankara kwa simu (akaunti ya AzamPay ya kampuni)."""
    from ..payment.service import _debt_with_invoice
    from ..payment.service import TOLERANCE

    company = _company(db)
    client = company_client(company)
    debt, invoice = _debt_with_invoice(db, data.debtId)
    balance = float(debt.debt or 0)
    if debt.status == "PAID" or balance < TOLERANCE:
        raise BadRequest("Ankara hii imeshalipwa yote")
    amount = round(float(data.amount or balance))
    if amount < 100:
        raise BadRequest("Kiasi cha chini cha malipo ya simu ni TSh 100")
    if amount > balance + TOLERANCE:
        raise BadRequest(f"Kiasi ({amount:,.0f}) kinazidi deni ({balance:,.0f})")
    phone = data.phone or (invoice.customer[0].phoneNumber if invoice and invoice.customer else None)
    msisdn = normalize(phone, required=True)
    provider = azampay.provider_name(data.provider or azampay.guess_provider(msisdn))
    row = OnlinePayment(purpose="INVOICE", company_id=company.id, externalId=_external_id(), provider=provider,
                        msisdn=msisdn, amount=float(amount), currency="TZS", debt_id=debt.id,
                        invoice_id=invoice.id if invoice else None,
                        invoiceNumber=invoice.invoiceNumber if invoice else None,
                        user_id=getattr(user, "id", None), username=getattr(user, "username", None))
    return out(_start(db, row, client))


# ------------------------------------------------------------------ hali

def _expire(db: Session, row: OnlinePayment) -> None:
    if row.status == "PENDING" and row.created_at and \
            utc_now() - row.created_at > timedelta(minutes=max(config.ONLINE_PAY_TIMEOUT_MINUTES, 2)):
        row.status = "EXPIRED"
        row.message = "Mteja hakuthibitisha kwa wakati - jaribu tena"
        row.completedAt = utc_now()
        db.commit()


def get(db: Session, payment_id, company_id=None) -> dict:
    from ..core.dao import to_uuid

    pk = to_uuid(payment_id)
    with tenant.system():
        row = db.get(OnlinePayment, pk) if pk else None
        if row is None or (company_id is not None and str(row.company_id) != str(company_id)):
            raise NotFound("Malipo hayapo")
        _expire(db, row)
        return out(row)


def out(row: OnlinePayment) -> dict:
    return {"id": str(row.id), "purpose": row.purpose, "status": row.status, "provider": row.provider,
            "msisdn": row.msisdn, "amount": row.amount, "currency": row.currency, "message": row.message,
            "externalId": row.externalId, "gatewayRef": row.gatewayRef, "operatorRef": row.operatorRef,
            "invoiceId": str(row.invoice_id) if row.invoice_id else None, "invoiceNumber": row.invoiceNumber,
            "planId": str(row.plan_id) if row.plan_id else None, "periods": row.periods,
            "couponCode": row.couponCode, "discount": row.discount,
            "companyId": str(row.company_id), "username": row.username,
            "createdAt": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
            "completedAt": row.completedAt.isoformat(timespec="seconds") if row.completedAt else None}


def list_payments(db: Session, company_id=None, purpose: str | None = None, status: str | None = None,
                  limit: int = 100) -> list[dict]:
    from ..saas.company.model import Company

    with tenant.system():
        q = db.query(OnlinePayment)
        if company_id is not None:
            q = q.filter(OnlinePayment.company_id == company_id)
        if purpose:
            q = q.filter(OnlinePayment.purpose == purpose.upper())
        if status:
            q = q.filter(OnlinePayment.status == status.upper())
        rows = q.order_by(OnlinePayment.created_at.desc()).limit(max(1, min(limit, 500))).all()
        for r in rows:
            _expire(db, r)
        names = {}
        if company_id is None and rows:
            names = {c.id: (c.name, c.slug) for c in
                     db.query(Company).filter(Company.id.in_({r.company_id for r in rows})).all()}
        return [{**out(r), "companyName": names.get(r.company_id, (None, None))[0],
                 "companySlug": names.get(r.company_id, (None, None))[1]} for r in rows]


# ------------------------------------------------------------------ callback ya AzamPay

def callback(db: Session, body: dict, token: str, slug: str | None = None) -> dict:
    """
    AzamPay inaripoti matokeo. URL ina siri (token) - bila hiyo ombi linakataliwa (404).
    Kila malipo yanashughulikiwa mara moja tu (callback ikirudiwa inapuuzwa).
    """
    from ..saas.company.model import Company

    body = body if isinstance(body, dict) else {}
    with tenant.system():
        company = None
        if slug is None:
            if not hmac.compare_digest(token, _token("platform")):
                raise NotFound("Not found")
            purpose = "SUBSCRIPTION"
        else:
            company = db.query(Company).filter(Company.slug == slug).first()
            if company is None or not hmac.compare_digest(token, _token(f"company:{company.id}")):
                raise NotFound("Not found")
            purpose = "INVOICE"
        ref = str(body.get("utilityref") or body.get("externalreference") or body.get("externalId") or "").strip()
        row = db.query(OnlinePayment).filter(OnlinePayment.externalId == ref).first() if ref else None
        if row is None or row.purpose != purpose or (company is not None and row.company_id != company.id):
            logger.warning("AzamPay callback for unknown payment %r (%s)", ref, slug or "platform")
            return {"ok": False, "reason": "unknown payment"}
        if row.status == "SUCCESS":
            return {"ok": True, "duplicate": True}
        status = str(body.get("transactionstatus") or body.get("status") or "").strip().lower()
        row.payload = body
        row.operatorRef = str(body.get("reference") or body.get("mnoreference") or "")[:120] or row.operatorRef
        row.message = str(body.get("message") or "")[:300] or row.message
        if status != "success":
            row.status = "FAILED"
            row.completedAt = utc_now()
            db.commit()
            _notify_failed(row)
            return {"ok": True, "status": row.status}
        try:
            paid = float(body.get("amount") or row.amount)
        except (TypeError, ValueError):
            paid = row.amount
        if paid + 0.5 < row.amount:
            row.status = "FAILED"
            row.message = f"Kiasi kilicholipwa ({paid:,.0f}) ni pungufu ya kilichoombwa ({row.amount:,.0f})"
            row.completedAt = utc_now()
            db.commit()
            return {"ok": True, "status": row.status}
        row.status = "SUCCESS"
        row.completedAt = utc_now()
        db.commit()
    try:
        _apply(db, row)
    except Exception:
        logger.exception("Online payment %s succeeded but could not be applied", row.externalId)
        db.rollback()
        with tenant.system():
            row = db.merge(row)
            row.message = "Pesa imepokelewa lakini haikurekodiwa yenyewe - irekodi kwa mkono"
            db.commit()
        if row.purpose == "SUBSCRIPTION":
            from ..saas.notice.service import notify

            notify("ONLINE_UNAPPLIED", "PAYMENTS", f"Malipo ya simu TZS {row.amount:,.0f} hayakurekodiwa yenyewe",
                   f"{row.provider} {row.msisdn} · ref {row.operatorRef or row.externalId} - yarekodi kwa mkono",
                   link="onlinepay", company_id=row.company_id, urgent=True)
    return {"ok": True, "status": "SUCCESS"}


def _apply(db: Session, row: OnlinePayment) -> None:
    if row.purpose == "SUBSCRIPTION":
        from ..saas.subscription import schema as sub_schema, service as subscriptions

        with tenant.system():
            payment = subscriptions.record_payment(db, sub_schema.RecordPayment(
                company_id=row.company_id, plan_id=row.plan_id, periods=row.periods or 1, amount=row.amount,
                currency="TZS", method=f"AzamPay {row.provider}", reference=row.operatorRef or row.externalId,
                note=f"Malipo ya simu {row.msisdn}", couponCode=row.couponCode, discount=row.discount,
                startMode=row.startMode), by="AzamPay")
            row = db.merge(row)
            row.applied_id = payment.id
            db.commit()
        from ..saas.company.model import Company
        from ..saas.notice.service import notify

        with tenant.system():
            company = db.get(Company, row.company_id)
        notify("ONLINE_PAID", "PAYMENTS",
               f"Malipo ya simu yamepokelewa: {company.name if company else '-'} · TZS {row.amount:,.0f}",
               f"{row.provider} {row.msisdn} · ref {row.operatorRef or row.externalId} · subscription imeongezwa",
               link="onlinepay", company_id=row.company_id)
        return

    from ..payment import schema as pay_schema, service as payments
    from ..saas.company.model import Company

    with tenant.system():
        company = db.get(Company, row.company_id)
    with tenant.use_company(company.id, company.slug):
        debt, _ = payments._debt_with_invoice(db, row.debt_id)
        balance = float(debt.debt or 0)
        amount = min(row.amount, balance) if balance > 0 else 0
        note = f"AzamPay {row.provider} {row.operatorRef or ''} ({row.msisdn})".strip()
        if amount <= 0:
            with tenant.system():
                r = db.merge(row)
                r.message = "Pesa imepokelewa lakini ankara ilikuwa imeshalipwa - rudisha au weka kwenye ankara nyingine"
                db.commit()
            return
        if amount < row.amount:
            note += f" - zimezidi TSh {row.amount - amount:,.0f}"
        payment = payments.create_payment(db, pay_schema.CreatePayment(
            paid=amount, debtId=debt.id, instituteId=_institute(db, company, row.user_id), currency="TZS", note=note),
            row.user_id)
        from ..notification.service import notify

        notify(db, "PAYMENT", "select", kind="ONLINE_PAYMENT",
               title=f"Malipo ya simu TSh {amount:,.0f} · ankara {row.invoiceNumber or '-'}",
               body=f"{row.provider} {row.msisdn} · risiti {payment.receiptNumber}",
               link=f"invoice:{row.invoice_id}" if row.invoice_id else None)
        db.commit()
    with tenant.system():
        r = db.merge(row)
        r.applied_id = payment.id
        db.commit()


def _institute(db: Session, company, user_id=None):
    """Akaunti ya kupokelea malipo ya simu: iliyochaguliwa kwenye mipangilio, au "AzamPay" (inaundwa yenyewe)."""
    from ..settings.institute.model import Institute

    chosen = (company.settings or {}).get("AZAMPAY_INSTITUTE_ID")
    if chosen:
        found = db.query(Institute).filter(Institute.id == chosen).first()
        if found is not None:
            return found.id
    found = db.query(Institute).filter(Institute.accountNo == "AZAMPAY").first()
    if found is None:
        found = Institute(name="AzamPay (malipo ya simu)", accountNo="AZAMPAY", currencyType="TZS", logsId=user_id)
        db.add(found)
        db.flush()
    return found.id


def _notify_failed(row: OnlinePayment) -> None:
    if row.purpose != "INVOICE":
        return
    try:
        from ..db import SessionLocal
        from ..notification.service import notify
        from ..saas.company.model import Company

        db = SessionLocal()
        try:
            with tenant.system():
                company = db.get(Company, row.company_id)
            with tenant.use_company(company.id, company.slug):
                notify(db, "PAYMENT", "insert", kind="ONLINE_PAYMENT_FAILED",
                       title=f"Malipo ya simu hayakukamilika · ankara {row.invoiceNumber or '-'}",
                       body=f"{row.provider} {row.msisdn}: {row.message or 'imekataliwa'}",
                       link=f"invoice:{row.invoice_id}" if row.invoice_id else None)
                db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("Online payment failure notice failed")
