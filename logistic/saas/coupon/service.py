"""
Coupon za punguzo:
  - wewe (FINANCE/OWNER) unaunda: KARIBU20 = 20% kwa kila malipo, au AMOUNT 10000 = TSh 10,000 pungufu
  - kampuni inaiweka wakati wa kulipia (simu au taarifa ya malipo) - kiasi kinapunguzwa
  - matumizi yanahesabiwa malipo yakithibitishwa (maxUses, maxPerCompany)
"""
import re
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.base_model import utc_now
from ...core.exceptions import BadRequest, Conflict, NotFound
from .model import Coupon, CouponUse


def _code(value: str) -> str:
    code = re.sub(r"[^A-Z0-9_-]", "", (value or "").strip().upper())
    if len(code) < 3:
        raise BadRequest("Code ya coupon: herufi/namba 3 au zaidi")
    return code


def list_all(db: Session) -> list[Coupon]:
    return db.query(Coupon).order_by(Coupon.created_at.desc()).all()


def save(db: Session, data, by: str) -> Coupon:
    kind = (data.kind or "PERCENT").upper()
    if kind not in ("PERCENT", "AMOUNT"):
        raise BadRequest("Aina: PERCENT au AMOUNT")
    if kind == "PERCENT" and data.value > 100:
        raise BadRequest("Asilimia isizidi 100")
    code = _code(data.code)
    other = db.query(Coupon).filter(Coupon.code == code).first()
    if other is not None and (data.id is None or other.id != data.id):
        raise Conflict("Code hii ipo tayari")
    coupon = db.get(Coupon, data.id) if data.id else None
    if data.id and coupon is None:
        raise NotFound("Coupon haipo")
    if coupon is None:
        coupon = Coupon(createdBy=by)
        db.add(coupon)
    coupon.code, coupon.description, coupon.kind, coupon.value = code, data.description, kind, float(data.value)
    coupon.planIds = [str(p) for p in data.planIds] if data.planIds else None
    coupon.company_id = data.company_id
    coupon.maxUses, coupon.maxPerCompany = data.maxUses, data.maxPerCompany
    coupon.validFrom, coupon.validUntil, coupon.active = data.validFrom, data.validUntil, data.active
    db.commit()
    db.refresh(coupon)
    return coupon


def delete(db: Session, coupon_id) -> dict:
    coupon = db.get(Coupon, uuid.UUID(str(coupon_id)))
    if coupon is None:
        raise NotFound("Coupon haipo")
    if coupon.used:
        coupon.active = False  # imeshatumika: inazimwa (historia inabaki)
    else:
        db.delete(coupon)
    db.commit()
    return {"ok": True}


def evaluate(db: Session, code: str | None, company_id, plan, periods: int) -> dict:
    """Bei kabla/baada ya punguzo. Kosa (BadRequest) kama coupon haifai."""
    gross = round(float(plan.price or 0) * int(periods), 2)
    if not code or not code.strip():
        return {"code": None, "gross": gross, "discount": 0.0, "amount": gross}
    coupon = db.query(Coupon).filter(Coupon.code == _code(code)).first()
    now = utc_now()
    if coupon is None or not coupon.active:
        raise BadRequest("Coupon hii haipo au imezimwa")
    if coupon.validFrom and now < coupon.validFrom:
        raise BadRequest("Coupon hii bado haijaanza kutumika")
    if coupon.validUntil and now > coupon.validUntil:
        raise BadRequest("Muda wa coupon hii umeisha")
    if coupon.company_id and str(coupon.company_id) != str(company_id):
        raise BadRequest("Coupon hii si ya kampuni yenu")
    if coupon.planIds and str(plan.id) not in coupon.planIds:
        raise BadRequest("Coupon hii haihusu mpango huu")
    if coupon.maxUses is not None and coupon.used >= coupon.maxUses:
        raise BadRequest("Coupon hii imeshatumika mara zote zinazoruhusiwa")
    mine = (db.query(func.count(CouponUse.id))
            .filter(CouponUse.coupon_id == coupon.id, CouponUse.company_id == company_id).scalar()) or 0
    if mine >= (coupon.maxPerCompany or 1):
        raise BadRequest("Kampuni yenu imeshatumia coupon hii")
    if (plan.currency or "TZS").upper() != "TZS" and coupon.kind == "AMOUNT":
        raise BadRequest("Coupon ya kiasi (TSh) ni kwa mipango ya TZS tu")
    discount = gross * coupon.value / 100.0 if coupon.kind == "PERCENT" else min(float(coupon.value), gross)
    discount = round(min(discount, gross), 2)
    return {"code": coupon.code, "gross": gross, "discount": discount, "amount": round(gross - discount, 2),
            "kind": coupon.kind, "value": coupon.value, "description": coupon.description}


def record_use(db: Session, code: str | None, company_id, payment_id, discount: float) -> None:
    """Malipo yamethibitishwa: matumizi ya coupon yanahesabiwa (mara moja kwa kila malipo)."""
    if not code:
        return
    coupon = db.query(Coupon).filter(Coupon.code == code.strip().upper()).first()
    if coupon is None:
        return
    if payment_id and db.query(CouponUse.id).filter(CouponUse.payment_id == payment_id).first():
        return
    db.add(CouponUse(coupon_id=coupon.id, company_id=company_id, payment_id=payment_id, discount=discount or 0))
    coupon.used = int(coupon.used or 0) + 1
    db.commit()
