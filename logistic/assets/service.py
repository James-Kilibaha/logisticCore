"""
Mali za kudumu: ununuzi unatoka kwenye akaunti ya fedha (sio matumizi), na uchakavu wa kila mwezi
((gharama - thamani ya mwisho) / miezi ya matumizi) unaingia kwenye Faida/Hasara kama gharama.
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..core.audit import note
from ..core.dao import to_uuid
from ..core.exceptions import BadRequest, NotFound
from ..core.utils import local_now, parse_date, whole
from . import schema
from .model import ASSET_CATEGORIES, FixedAsset


def _months_between(a: date, b: date) -> int:
    """Miezi kamili kutoka mwezi wa `a` mpaka mwezi wa `b` (mwezi wa ununuzi unahesabiwa)."""
    return max((b.year - a.year) * 12 + (b.month - a.month) + 1, 0)


def monthly(a: FixedAsset) -> float:
    return max((a.cost or 0) - (a.salvage or 0), 0) / max(a.lifeMonths or 1, 1)


def _end(a: FixedAsset, upto: date) -> date:
    disposed = parse_date(a.disposedOn) if a.disposedOn else None
    return min(upto, disposed) if disposed else upto


def accumulated(a: FixedAsset, upto: date) -> float:
    start = parse_date(a.purchaseDate)
    if start is None or upto < start:
        return 0.0
    months = min(_months_between(start, _end(a, upto)), a.lifeMonths or 1)
    return round(min(monthly(a) * months, max((a.cost or 0) - (a.salvage or 0), 0)), 2)


def book_value(a: FixedAsset, upto: date | None = None) -> float:
    upto = upto or local_now().date()
    if a.disposedOn and parse_date(a.disposedOn) and parse_date(a.disposedOn) <= upto:
        return 0.0
    return round((a.cost or 0) - accumulated(a, upto), 2)


def _prev_month(d: date) -> date:
    return d.replace(day=1) - timedelta(days=1)


def depreciation_between(db: Session, start: date, end: date) -> float:
    """Uchakavu wa mali zote kwa kipindi [start, end] (kwa Faida/Hasara)."""
    return round(sum(accumulated(a, end) - accumulated(a, _prev_month(start))
                     for a in db.query(FixedAsset).filter(FixedAsset.isBlocked.is_(False)).all()), 2)


def book_value_total(db: Session) -> float:
    return round(sum(book_value(a) for a in db.query(FixedAsset).filter(FixedAsset.isBlocked.is_(False)).all()), 2)


def _row(db: Session, a: FixedAsset) -> dict:
    from ..settings.institute.model import Institute
    from ..settings.office.model import Office

    inst = db.get(Institute, a.institute_id) if a.institute_id else None
    office = db.get(Office, a.office_id) if a.office_id else None
    today = local_now().date()
    return {"id": str(a.id), "name": a.name, "category": a.category, "cost": a.cost, "currency": a.currency,
            "amountOriginal": a.amountOriginal, "purchaseDate": a.purchaseDate, "lifeMonths": a.lifeMonths,
            "salvage": a.salvage, "monthly": round(monthly(a), 2), "accumulated": accumulated(a, today),
            "bookValue": book_value(a, today), "institute_id": str(a.institute_id) if a.institute_id else None,
            "institute": inst.name if inst else None, "office_id": str(a.office_id) if a.office_id else None,
            "office": office.name if office else None, "serial": a.serial, "note": a.note,
            "disposedOn": a.disposedOn, "disposalAmount": a.disposalAmount,
            "created_at": a.created_at.isoformat() if a.created_at else None}


def list_all(db: Session) -> dict:
    rows = [_row(db, a) for a in db.query(FixedAsset).filter(FixedAsset.isBlocked.is_(False))
            .order_by(FixedAsset.purchaseDate.desc()).all()]
    return {"items": rows, "cost": round(sum(r["cost"] for r in rows), 2),
            "accumulated": round(sum(r["accumulated"] for r in rows), 2),
            "bookValue": round(sum(r["bookValue"] for r in rows), 2)}


def _get(db: Session, asset_id) -> FixedAsset:
    a = db.get(FixedAsset, to_uuid(asset_id))
    if a is None or a.isBlocked:
        raise NotFound("Mali haipo")
    return a


def save(db: Session, data: schema.AssetSave, user_id, asset_id=None) -> dict:
    from ..accounting.locks import ensure_open
    from ..accounting.service import _account, _rate

    day = parse_date(data.purchaseDate)
    if day is None or day > local_now().date():
        raise BadRequest("Tarehe ya ununuzi si sahihi")
    category = (data.category or "OTHER").upper()
    if category not in ASSET_CATEGORIES:
        raise BadRequest("Aina ya mali si sahihi")
    if data.institute_id is not None:
        _account(db, data.institute_id)
    code, rate = _rate(db, data.currency)
    cost = round(data.cost * rate, 2)
    if data.salvage >= cost:
        raise BadRequest("Thamani ya mwisho iwe chini ya gharama")
    local = code in ("TZS", "TSH") and rate == 1.0
    fields = {"name": data.name.strip(), "category": category, "cost": cost, "currency": code,
              "amountOriginal": None if local else data.cost, "rate": None if local else rate,
              "purchaseDate": day.isoformat(), "lifeMonths": data.lifeMonths, "salvage": round(data.salvage, 2),
              "institute_id": data.institute_id, "office_id": data.office_id,
              "serial": (data.serial or "").strip() or None, "note": (data.note or "").strip() or None}
    if asset_id is None:
        ensure_open(db)
        a = FixedAsset(**fields, logsId=user_id)
        db.add(a)
    else:
        a = _get(db, asset_id)
        ensure_open(db, a.created_at)
        for k, v in fields.items():
            setattr(a, k, v)
    db.commit()
    note(f"Mali ya kudumu: {a.name} TSh {whole(a.cost)} (miezi {a.lifeMonths})")
    return _row(db, a)


def dispose(db: Session, asset_id, data: schema.Dispose, user_id) -> dict:
    from ..accounting.locks import ensure_open
    from ..accounting.service import _account

    ensure_open(db)
    a = _get(db, asset_id)
    day = parse_date(data.date)
    if day is None or day < parse_date(a.purchaseDate):
        raise BadRequest("Tarehe si sahihi")
    if data.institute_id is not None:
        _account(db, data.institute_id)
    value = round((a.cost or 0) - accumulated(a, day), 2)
    a.disposedOn, a.disposalAmount = day.isoformat(), round(data.amount or 0, 2)
    a.disposal_institute_id = data.institute_id
    db.commit()
    gain = round((data.amount or 0) - value, 2)
    note(f"Mali '{a.name}' imeondolewa: imepata TSh {whole(data.amount or 0)} "
         f"({'faida' if gain >= 0 else 'hasara'} TSh {whole(abs(gain))})")
    return _row(db, a)


def delete(db: Session, asset_id) -> bool:
    from ..accounting.locks import ensure_open

    a = _get(db, asset_id)
    ensure_open(db, a.created_at)
    db.delete(a)
    db.commit()
    note(f"Mali ya kudumu imefutwa: {a.name}")
    return True


def disposal_gain_between(db: Session, start: date, end: date) -> float:
    """Faida(+)/hasara(-) ya kuuza/kuondoa mali ndani ya kipindi (kiasi kilichopatikana - thamani iliyobaki)."""
    total = 0.0
    for a in db.query(FixedAsset).filter(FixedAsset.isBlocked.is_(False), FixedAsset.disposedOn.isnot(None)).all():
        d = parse_date(a.disposedOn)
        if d and start <= d <= end:
            total += (a.disposalAmount or 0) - ((a.cost or 0) - accumulated(a, d))
    return round(total, 2)
