"""
Subscription za kampuni: hali ya sasa, mipaka ya mpango, malipo na vikumbusho.

Hali (state):
  TRIAL / ACTIVE : kipindi kinachoendelea sasa
  GRACE          : kimeisha ndani ya SUBSCRIPTION_GRACE_DAYS - kazi zote bado zinaruhusiwa
  EXPIRED / NONE : mfumo ni wa KUSOMA TU (readOnly) hadi walipie
"""
import calendar
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import config
from ...core import tenant
from ...core.base_model import utc_now
from ...core.exceptions import BadRequest, NotFound, PaymentRequired
from ..plan.model import Plan
from ..plan.service import OPTIONAL_MODULES
from . import schema
from .dao import PaymentDao, SubscriptionDao
from .model import Subscription, SubscriptionPayment

logger = logging.getLogger(__name__)

CACHE_SECONDS = 30
_lock = threading.Lock()
_cache: dict[uuid.UUID, tuple[float, dict]] = {}


def add_months(when: datetime, months: int) -> datetime:
    month = when.month - 1 + months
    year = when.year + month // 12
    month = month % 12 + 1
    day = min(when.day, calendar.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)


def invalidate(cid=None) -> None:
    with _lock:
        if cid is None:
            _cache.clear()
        else:
            _cache.pop(cid if isinstance(cid, uuid.UUID) else uuid.UUID(str(cid)), None)


def _plan_dict(plan: Plan | None, company=None) -> dict | None:
    """Mpango + mipaka HALISI ya kampuni (mpango + nafasi za ziada ulizoipa). NULL = bila kikomo."""
    if plan is None:
        return None

    def limit(base, extra):
        return None if base is None else int(base) + int(extra or 0)

    extra = {"users": int(getattr(company, "extraUsers", 0) or 0),
             "offices": int(getattr(company, "extraOffices", 0) or 0),
             "invoicesPerMonth": int(getattr(company, "extraInvoicesPerMonth", 0) or 0)}
    return {"id": str(plan.id), "code": plan.code, "name": plan.name, "price": plan.price, "currency": plan.currency,
            "months": plan.months,
            "maxUsers": limit(plan.maxUsers, extra["users"]),
            "maxOffices": limit(plan.maxOffices, extra["offices"]),
            "maxInvoicesPerMonth": limit(plan.maxInvoicesPerMonth, extra["invoicesPerMonth"]),
            "planLimits": {"maxUsers": plan.maxUsers, "maxOffices": plan.maxOffices,
                           "maxInvoicesPerMonth": plan.maxInvoicesPerMonth},
            "extra": extra,
            "modules": plan.modules}


def compute(db: Session, cid) -> dict:
    dao = SubscriptionDao(db)
    now = utc_now()
    current = dao.covering_now(cid)
    latest = dao.latest(cid)
    grace = timedelta(days=max(config.SUBSCRIPTION_GRACE_DAYS, 0))
    if current is not None:
        status, read_only = current.status, False
        # mwisho halisi = mwisho wa kipindi cha mbali zaidi (vipindi vilivyolipiwa mapema vinaungana)
        ends = latest.endsAt if latest is not None and latest.endsAt > current.endsAt else current.endsAt
        sub = current
    elif latest is not None and latest.startsAt > now:
        # kipindi cha baadaye tu (hakuna kinachoendelea sasa) - kinaanza karibuni: kiruhusiwe
        status, read_only, ends, sub = latest.status, False, latest.endsAt, latest
    elif latest is not None and now <= latest.endsAt + grace:
        status, read_only, ends, sub = "GRACE", False, latest.endsAt, latest
    elif latest is not None:
        status, read_only, ends, sub = "EXPIRED", True, latest.endsAt, latest
    else:
        status, read_only, ends, sub = "NONE", True, None, None
    days_left = None
    if ends is not None:
        days_left = int((ends - now).total_seconds() // 86400) if ends > now else -int((now - ends).total_seconds() // 86400)
    plan = sub.plan if sub is not None else None
    from ..company.model import Company

    company = db.get(Company, cid if isinstance(cid, uuid.UUID) else uuid.UUID(str(cid)))
    upcoming = None
    if current is not None:
        nxt = [s for s in dao.active_periods(cid) if s.startsAt > now and s.plan_id != current.plan_id]
        if nxt:
            first = min(nxt, key=lambda s: s.startsAt)
            upcoming = {"planId": str(first.plan_id), "planName": first.plan.name if first.plan else None,
                        "startsAt": first.startsAt.isoformat(), "endsAt": first.endsAt.isoformat()}
    return {
        "upcoming": upcoming,
        "status": status,
        "readOnly": read_only,
        "endsAt": ends.isoformat() if ends else None,
        "graceEndsAt": (ends + grace).isoformat() if ends else None,
        "daysLeft": days_left,
        "plan": _plan_dict(plan, company),
        "modules": OPTIONAL_MODULES if plan is None or plan.modules is None else list(plan.modules),
    }


def state(cid) -> dict:
    """Hali ya subscription (cache ya sekunde CACHE_SECONDS)."""
    if not isinstance(cid, uuid.UUID):
        cid = uuid.UUID(str(cid))
    now = time.time()
    with _lock:
        hit = _cache.get(cid)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    from ...db import SessionLocal

    with tenant.system():
        db = SessionLocal()
        try:
            value = compute(db, cid)
        finally:
            db.close()
    with _lock:
        _cache[cid] = (now, value)
    return value


# ------------------------------------------------------------------ mipaka ya mpango

def module_allowed(module_value: str) -> bool:
    """Moduli za msingi ziko kwenye kila mpango; za ziada zinategemea mpango."""
    cid = tenant.company_id()
    if cid is None or module_value not in OPTIONAL_MODULES:
        return True
    return module_value in state(cid)["modules"]


def ensure_module(module_value: str) -> None:
    if not module_allowed(module_value):
        raise PaymentRequired(f"Huduma hii ({module_value.title()}) haipo kwenye mpango wenu - pandisha mpango "
                              f"/ this feature is not in your plan")


def usage(db: Session, cid) -> dict:
    from ...invoice.model import Invoice
    from ...settings.office.model import Office
    from ...user.model import User

    start = utc_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with tenant.system():
        users = db.query(func.count(User.id)).filter(User.company_id == cid, User.active != 0).scalar() or 0
        offices = (db.query(func.count(Office.id))
                   .filter(Office.company_id == cid, Office.isBlocked.is_(False)).scalar() or 0)
        invoices = (db.query(func.count(Invoice.id))
                    .filter(Invoice.company_id == cid, Invoice.created_at >= start).scalar() or 0)
    return {"users": int(users), "offices": int(offices), "invoicesThisMonth": int(invoices)}


_LIMITS = {
    "users": ("maxUsers", "watumiaji", "users"),
    "offices": ("maxOffices", "ofisi", "offices"),
    "invoicesThisMonth": ("maxInvoicesPerMonth", "ankara za mwezi huu", "invoices this month"),
}


def check_limit(db: Session, kind: str) -> None:
    """Inakataa (402) kuongeza kitu kipya kama mpango umefikia kikomo chake."""
    cid = tenant.company_id()
    if cid is None:
        return
    plan = state(cid).get("plan") or {}
    field, sw, en = _LIMITS[kind]
    limit = plan.get(field)
    if limit is None:
        return
    used = usage(db, cid)[kind]
    if used >= limit:
        raise PaymentRequired(f"Mpango wenu ({plan.get('name')}) unaruhusu {sw} {limit} tu - pandisha mpango "
                              f"/ your plan allows {limit} {en}")


# ------------------------------------------------------------------ vipindi

def _plan(db: Session, plan_id) -> Plan:
    plan = db.get(Plan, plan_id if isinstance(plan_id, uuid.UUID) else uuid.UUID(str(plan_id)))
    if plan is None:
        raise NotFound("Mpango haupo")
    return plan


def _next_start(db: Session, cid) -> datetime:
    latest = SubscriptionDao(db).latest(cid)
    now = utc_now()
    if latest is None or latest.endsAt < now:
        return now
    if latest.status == "TRIAL":
        return now  # kulipia kunamaliza majaribio papo hapo
    return latest.endsAt


def _end_trials(db: Session, cid) -> None:
    now = utc_now()
    for sub in SubscriptionDao(db).active_periods(cid):
        if sub.status == "TRIAL" and sub.endsAt > now:
            sub.endsAt = now - timedelta(seconds=1)


def start_trial(db: Session, cid, plan: Plan, days: int | None = None, by: str | None = None) -> Subscription:
    now = utc_now()
    sub = Subscription(company_id=cid, plan_id=plan.id, status="TRIAL", startsAt=now,
                       endsAt=now + timedelta(days=days or config.TRIAL_DAYS), note="Majaribio / trial",
                       createdBy=by)
    db.add(sub)
    db.commit()
    invalidate(cid)
    return sub


# ------------------------------------------------------------------ kubadilisha mpango (upgrade / downgrade)
#
# Mpango mpya ukiwa:
#   UPGRADE   (ghali zaidi kwa mwezi) - unaanza SASA; siku zilizobaki za mpango uliolipiwa zinaongezwa juu yake.
#   DOWNGRADE (rahisi zaidi kwa mwezi) - QUEUE (chaguo-msingi): unasubiri siku za mpango mkubwa ziishe, kisha unaanza;
#                                         NOW: mteja amekubali siku zilizobaki zifutwe - unaanza sasa.
#   SAME / NEW - mpango ule ule (au bei sawa) unaongezwa mwishoni; hakuna mpango uliolipiwa -> unaanza sasa.
# Siku za majaribio (TRIAL) si za kulipiwa - hazihamishwi.

START_MODES = ("QUEUE", "NOW")


def _monthly(plan: Plan) -> float:
    return float(plan.price or 0) / max(int(plan.months or 1), 1)


def _days(delta: timedelta) -> int:
    return max(int(round(delta.total_seconds() / 86400)), 0)


def _change(db: Session, cid, plan: Plan, periods: int, now: datetime) -> dict:
    rows = [s for s in SubscriptionDao(db).active_periods(cid) if s.status == "ACTIVE" and s.endsAt > now]
    remaining = sum((s.endsAt - max(s.startsAt, now) for s in rows), timedelta())
    current = min(rows, key=lambda s: s.startsAt) if rows else None
    if current is None:
        kind = "NEW"
    elif current.plan_id == plan.id or abs(_monthly(plan) - _monthly(current.plan)) < 0.01:
        kind = "SAME"
    else:
        kind = "UPGRADE" if _monthly(plan) > _monthly(current.plan) else "DOWNGRADE"
    span = max(plan.months, 1) * max(periods, 1)
    queued_start = max(s.endsAt for s in rows) if rows else now
    return {"kind": kind, "rows": rows, "remaining": remaining, "current": current, "span": span,
            "queuedStart": queued_start}


def plan_change(db: Session, cid, plan_id, periods: int = 1) -> dict:
    """Maelezo kabla ya kulipa: mpango mpya utaanza lini, siku zipi zinaongezwa au zitafutwa."""
    plan = _plan(db, plan_id)
    now = utc_now()
    c = _change(db, cid, plan, periods, now)
    days = _days(c["remaining"])
    now_end = add_months(now, c["span"])
    queue_start = c["queuedStart"] if c["kind"] in ("SAME", "DOWNGRADE") else now
    out = {
        "kind": c["kind"],
        "plan": {"id": str(plan.id), "name": plan.name},
        "currentPlan": {"id": str(c["current"].plan_id), "name": c["current"].plan.name} if c["current"] else None,
        "remainingDays": days,
        "currentEndsAt": c["queuedStart"].isoformat() if c["rows"] else None,
    }
    if c["kind"] == "UPGRADE":
        out.update(startsAt=now.isoformat(), endsAt=(now_end + c["remaining"]).isoformat(), carriedDays=days)
    elif c["kind"] == "DOWNGRADE":
        out.update(queue={"startsAt": queue_start.isoformat(), "endsAt": add_months(queue_start, c["span"]).isoformat()},
                   now={"startsAt": now.isoformat(), "endsAt": now_end.isoformat(), "forfeitDays": days},
                   startsAt=queue_start.isoformat(), endsAt=add_months(queue_start, c["span"]).isoformat())
    else:
        out.update(startsAt=queue_start.isoformat(), endsAt=add_months(queue_start, c["span"]).isoformat())
    return out


def add_period(db: Session, cid, plan: Plan, periods: int = 1, by: str | None = None,
               note: str | None = None, mode: str | None = None) -> Subscription:
    now = utc_now()
    c = _change(db, cid, plan, periods, now)
    kind = c["kind"]
    mode = (mode or "QUEUE").upper()
    restart = kind == "UPGRADE" or (kind == "DOWNGRADE" and mode == "NOW")
    if restart:
        old_name = c["current"].plan.name
        days = _days(c["remaining"])
        for s in c["rows"]:
            if s.startsAt > now:
                s.status = "CANCELLED"
            else:
                s.endsAt = now - timedelta(seconds=1)
            s.note = ((s.note or "") + (f" · imehamishiwa {plan.name}" if kind == "UPGRADE"
                                         else f" · siku zimefutwa (amechagua {plan.name} sasa)")).strip(" ·")
        start = now
        end = add_months(now, c["span"])
        if kind == "UPGRADE":
            end += c["remaining"]
            note = f"{note or 'Malipo'} · siku {days} za {old_name} zimeongezwa"
        else:
            note = f"{note or 'Malipo'} · siku {days} za {old_name} zimefutwa"
    else:
        start = _next_start(db, cid)
        end = add_months(start, c["span"])
        if kind == "DOWNGRADE":
            note = f"{note or 'Malipo'} · inaanza baada ya {c['current'].plan.name} kuisha"
    _end_trials(db, cid)
    sub = Subscription(company_id=cid, plan_id=plan.id, status="ACTIVE", startsAt=start, endsAt=end, note=note,
                       createdBy=by)
    db.add(sub)
    db.commit()
    invalidate(cid)
    return sub


def _paid_message(prefix: str, sub: Subscription) -> str:
    """Ujumbe kwa kampuni baada ya malipo: mpango mdogo uliopangwa unaanza baadaye."""
    if sub.startsAt > utc_now() + timedelta(minutes=5):
        return (f"{prefix} - mpango {sub.plan.name if sub.plan else ''} utaanza {sub.startsAt:%d/%m/%Y} "
                f"(mpango wako wa sasa ukiisha) hadi {sub.endsAt:%d/%m/%Y}")
    return f"{prefix} - subscription hadi {sub.endsAt:%d/%m/%Y}"


def extend(db: Session, data: schema.Extend, by: str) -> Subscription:
    latest = SubscriptionDao(db).latest(data.company_id)
    plan = _plan(db, data.plan_id) if data.plan_id else (latest.plan if latest else None)
    if plan is None:
        raise BadRequest("Chagua mpango")
    status = data.status.strip().upper()
    if status not in ("ACTIVE", "TRIAL"):
        raise BadRequest("status: ACTIVE au TRIAL")
    start = _next_start(db, data.company_id) if status == "ACTIVE" else max(utc_now(), latest.endsAt if latest else utc_now())
    sub = Subscription(company_id=data.company_id, plan_id=plan.id, status=status, startsAt=start,
                       endsAt=start + timedelta(days=data.days), note=data.note or f"Siku {data.days} za ziada",
                       createdBy=by)
    db.add(sub)
    db.commit()
    invalidate(data.company_id)
    return sub


def change_plan(db: Session, data: schema.ChangePlan) -> Subscription:
    plan = _plan(db, data.plan_id)
    dao = SubscriptionDao(db)
    sub = dao.covering_now(data.company_id) or dao.latest(data.company_id)
    if sub is None:
        raise NotFound("Kampuni hii haina subscription")
    sub.plan_id = plan.id
    db.commit()
    db.refresh(sub)
    invalidate(data.company_id)
    return sub


def cancel(db: Session, subscription_id) -> Subscription:
    sub = SubscriptionDao(db).get(subscription_id)
    if sub is None:
        raise NotFound("Kipindi hakipo")
    sub.status = "CANCELLED"
    db.commit()
    invalidate(sub.company_id)
    return sub


def history(db: Session, cid) -> list[Subscription]:
    return SubscriptionDao(db).for_company(cid)


# ------------------------------------------------------------------ malipo

def submit_payment(db: Session, data: schema.SubmitPayment, submitted_by: str) -> SubscriptionPayment:
    cid = tenant.require_company_id()
    plan = _plan(db, data.plan_id)
    if not plan.isActive:
        raise BadRequest("Mpango huu haupatikani tena")
    reference = data.reference.strip()
    dup = (db.query(SubscriptionPayment.id)
           .filter(SubscriptionPayment.company_id == cid, func.lower(SubscriptionPayment.reference) == reference.lower(),
                   SubscriptionPayment.status != "REJECTED").first())
    if dup:
        raise BadRequest("Namba hii ya muamala imeshatumwa")
    from ..coupon import service as coupons

    price = coupons.evaluate(db, data.couponCode, cid, plan, data.periods)  # coupon isiyofaa -> kosa
    mode = (data.startMode or "QUEUE").upper()
    if mode not in START_MODES:
        raise BadRequest("startMode: QUEUE au NOW")
    payment = SubscriptionPayment(startMode=mode, company_id=cid, plan_id=plan.id, periods=data.periods, amount=data.amount,
                                  currency=data.currency.strip().upper() or "TZS", method=data.method.strip(),
                                  reference=reference, note=data.note, status="PENDING", submittedBy=submitted_by,
                                  couponCode=price["code"], discount=price["discount"] or None)
    db.add(payment)
    db.commit()
    db.refresh(payment)
    from ..company.model import Company
    from ..notice.service import notify

    with tenant.system():
        company = db.get(Company, cid)
    notify("PAYMENT_SUBMITTED", "PAYMENTS",
           f"Malipo mapya ya kuthibitisha: {company.name if company else '-'} · {payment.currency} {payment.amount:,.0f}",
           f"{plan.name} × {payment.periods} · {payment.method} · ref {payment.reference}",
           link=f"payment:{payment.id}", company_id=cid, urgent=True)
    return payment


def record_payment(db: Session, data: schema.RecordPayment, by: str) -> SubscriptionPayment:
    plan = _plan(db, data.plan_id)
    sub = add_period(db, data.company_id, plan, data.periods, by=by, note=data.note or "Malipo",
                     mode=data.startMode)
    payment = SubscriptionPayment(startMode=(data.startMode or "QUEUE").upper(), company_id=data.company_id, plan_id=plan.id, periods=data.periods,
                                  amount=data.amount, currency=data.currency.strip().upper() or "TZS",
                                  method=data.method, reference=data.reference, note=data.note,
                                  status="CONFIRMED", submittedBy=by, reviewedBy=by, reviewedAt=utc_now(),
                                  subscription_id=sub.id, couponCode=(data.couponCode or None) and data.couponCode.upper(),
                                  discount=data.discount)
    db.add(payment)
    db.commit()
    db.refresh(payment)
    if payment.couponCode:
        from ..coupon import service as coupons

        coupons.record_use(db, payment.couponCode, payment.company_id, payment.id, payment.discount or 0)
    notify_company(data.company_id, "SUBSCRIPTION_PAID", _paid_message("Malipo yamepokelewa", sub))
    _send_receipt(db, payment)
    return payment


def confirm_payment(db: Session, payment_id, by: str, note: str | None = None) -> SubscriptionPayment:
    payment = PaymentDao(db).get(payment_id)
    if payment is None:
        raise NotFound("Malipo hayapo")
    if payment.status != "PENDING":
        raise BadRequest(f"Malipo haya yameshashughulikiwa ({payment.status})")
    plan = _plan(db, payment.plan_id)
    sub = add_period(db, payment.company_id, plan, payment.periods, by=by,
                     note=f"Malipo {payment.reference or ''}".strip(), mode=payment.startMode)
    payment.status = "CONFIRMED"
    payment.reviewedBy = by
    payment.reviewedAt = utc_now()
    payment.subscription_id = sub.id
    if payment.couponCode:
        from ..coupon import service as coupons

        coupons.record_use(db, payment.couponCode, payment.company_id, payment.id, payment.discount or 0)
    if note:
        payment.note = ((payment.note or "") + f"\n[{by}] {note}").strip()
    db.commit()
    db.refresh(payment)
    notify_company(payment.company_id, "SUBSCRIPTION_PAID",
                   _paid_message(f"Malipo ({payment.reference}) yamethibitishwa", sub))
    _send_receipt(db, payment)
    return payment


def reject_payment(db: Session, payment_id, by: str, note: str | None = None) -> SubscriptionPayment:
    payment = PaymentDao(db).get(payment_id)
    if payment is None:
        raise NotFound("Malipo hayapo")
    if payment.status != "PENDING":
        raise BadRequest(f"Malipo haya yameshashughulikiwa ({payment.status})")
    payment.status = "REJECTED"
    payment.reviewedBy = by
    payment.reviewedAt = utc_now()
    if note:
        payment.note = ((payment.note or "") + f"\n[{by}] {note}").strip()
    db.commit()
    db.refresh(payment)
    notify_company(payment.company_id, "SUBSCRIPTION_REJECTED",
                   f"Malipo ({payment.reference}) hayakuthibitishwa" + (f": {note}" if note else ""))
    return payment


# ------------------------------------------------------------------ risiti

def receipt(db: Session, payment_id, company_id=None) -> tuple[bytes, str]:
    """PDF ya risiti ya malipo yaliyothibitishwa. `company_id`: kampuni inaweza kupata risiti zake tu."""
    from ..company.model import Company
    from . import receipt as receipt_pdf

    payment = PaymentDao(db).get(payment_id)
    if payment is None or (company_id is not None and str(payment.company_id) != str(company_id)):
        raise NotFound("Malipo hayapo / payment not found")
    if payment.status != "CONFIRMED":
        raise BadRequest("Risiti inapatikana kwa malipo yaliyothibitishwa tu / only confirmed payments have a receipt")
    company = db.get(Company, payment.company_id)
    sub = db.get(Subscription, payment.subscription_id) if payment.subscription_id else None
    return receipt_pdf.pdf(payment, company, sub), receipt_pdf.number(payment)


def _send_receipt(db: Session, payment: SubscriptionPayment) -> None:
    """Email ya risiti kwa kampuni (kama SMTP imewekwa na kampuni ina email)."""
    from ...core import mail
    from ..company.model import Company

    if not mail.configured():
        return
    try:
        company = db.get(Company, payment.company_id)
        if company is None or not mail.valid(company.email):
            return
        content, no = receipt(db, payment.id)
        body = (f"Habari {company.ownerName or company.name},\n\nTumepokea malipo yenu ya "
                f"{payment.currency} {payment.amount:,.0f} ({payment.reference or payment.method or '-'}). "
                f"Risiti {no} imeambatishwa.\n\nAhsante,\n{config.PLATFORM_NAME}")
        _email_company(company, f"{config.PLATFORM_NAME}: Risiti {no}", body, [(f"{no}.pdf", content, "application/pdf")])
    except Exception:
        logger.exception("Receipt email failed")


# ------------------------------------------------------------------ taarifa na vikumbusho

def notify_company(cid, kind: str, title: str, body: str | None = None) -> None:
    """Taarifa (popup) kwa watumiaji wa kampuni wenye ruhusa ya Mipangilio."""
    from ...db import SessionLocal
    from ...notification.service import notify

    try:
        with tenant.use_company(cid):
            db = SessionLocal()
            try:
                notify(db, "SETTING", "update", kind=kind, title=title, body=body, link="subscription")
                db.commit()
            finally:
                db.close()
    except Exception:
        logger.exception("Subscription notification failed")


def _sms_owner(company, text: str) -> bool:
    """SMS kwa mmiliki wa kampuni kupitia akaunti yako ya SMS (.env)."""
    from ...core.phone import try_normalize
    from ...sms.model import Sms
    from ...sms.service import _send_to_gateway

    phone = try_normalize(company.ownerPhone or company.phone)
    if not phone or not (config.SMS_CLIENT_ID and config.SMS_CLIENT_SECRET):
        return False
    try:
        _send_to_gateway(Sms(text=text, msisdn=phone, source=config.PLATFORM_SMS_SOURCE or config.SMS_SOURCE_NAME,
                             reference=f"SUB{uuid.uuid4().hex[:17].upper()}", coding=config.SMS_CODING,
                             smsFor="CUSTOM"))
        return True
    except Exception:
        logger.exception("Subscription SMS failed for %s", company.slug)
        return False


def _email_company(company, subject: str, body: str, attachments=None) -> None:
    """Email kwa kampuni (anwani yake ya email) kupitia SMTP ya .env - nyuma, bila kuzuia request."""
    from ...core import mail

    if mail.valid(company.email):
        mail.send_later(company.email, subject, body, attachments)


def _reminder(st: dict) -> tuple[str, str] | None:
    """(key, ujumbe) wa kikumbusho cha leo kwa hali hii ya subscription - None kama hakuna."""
    days = st["daysLeft"]
    if days is None or not st["endsAt"]:
        return None
    ends = st["endsAt"][:10]
    if st["status"] in ("TRIAL", "ACTIVE") and days in config.SUBSCRIPTION_REMIND_DAYS:
        what = "Majaribio" if st["status"] == "TRIAL" else "Subscription"
        return f"{ends}:D{days}", f"{what} ya {config.PLATFORM_NAME} inaisha baada ya siku {days} ({ends})"
    if st["status"] == "GRACE" and days == 0:
        return f"{ends}:END", f"Subscription ya {config.PLATFORM_NAME} imeisha leo - lipia ili kuendelea"
    if st["status"] == "EXPIRED" and days == -max(config.SUBSCRIPTION_GRACE_DAYS, 0) - 1:
        return f"{ends}:RO", "Subscription imeisha - mfumo sasa ni wa kusoma tu hadi mlipie"
    return None


REMINDER_KEY = "_subscriptionReminder"  # kwenye company.settings: kikumbusho cha mwisho kilichotumwa


def remind_expiring() -> dict:
    """
    Kila siku: vikumbusho siku SUBSCRIPTION_REMIND_DAYS kabla ya kuisha, siku ya kuisha na siku mfumo
    unapokuwa wa kusoma tu. Kila kikumbusho kinatumwa MARA MOJA tu (hata kazi ikiendeshwa mara mbili):
    taarifa ndani ya app + SMS kwa mmiliki + email ya kampuni.
    """
    from sqlalchemy.orm.attributes import flag_modified

    from ...db import SessionLocal
    from ..company import settings as company_settings
    from ..company.model import Company

    out = {"sent": 0, "sms": 0, "email": 0, "companies": []}
    with tenant.system():
        db = SessionLocal()
        try:
            companies = db.query(Company).filter(Company.status == "ACTIVE").all()
            for company in companies:
                invalidate(company.id)
                st = compute(db, company.id)
                found = _reminder(st)
                if found is None:
                    continue
                key, title = found
                if (company.settings or {}).get(REMINDER_KEY) == key:
                    continue  # kimeshatumwa
                notify_company(company.id, "SUBSCRIPTION_EXPIRING", title)
                pay = f" Malipo: {config.PLATFORM_PAYMENT_INFO}" if config.PLATFORM_PAYMENT_INFO else ""
                if _sms_owner(company, f"{company.name}: {title}.{pay}"[:450]):
                    out["sms"] += 1
                from ...core import mail

                if mail.configured() and mail.valid(company.email):
                    url = company_settings.app_url(company)
                    lines = [f"Habari {company.ownerName or company.name},", "", f"{title}.", ""]
                    if config.PLATFORM_PAYMENT_INFO:
                        lines += ["Jinsi ya kulipa:", config.PLATFORM_PAYMENT_INFO, ""]
                    lines += ["Baada ya kulipa, tuma taarifa ya malipo kwenye mfumo: Mipangilio -> Subscription"
                              + (f" ({url})" if url else "") + ".", ""]
                    if config.PLATFORM_SUPPORT_PHONE or config.PLATFORM_SUPPORT_EMAIL:
                        lines.append("Msaada: " + " / ".join(x for x in (config.PLATFORM_SUPPORT_PHONE,
                                                                         config.PLATFORM_SUPPORT_EMAIL) if x))
                    lines.append(config.PLATFORM_NAME)
                    _email_company(company, f"{config.PLATFORM_NAME}: {title}", "\n".join(lines))
                    out["email"] += 1
                company.settings = {**(company.settings or {}), REMINDER_KEY: key}
                flag_modified(company, "settings")
                db.commit()
                company_settings.invalidate(company.id)
                out["sent"] += 1
                out["companies"].append({"name": company.name, "slug": company.slug, "message": title})
        finally:
            db.close()
    return out
