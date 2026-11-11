"""
Namba za simu - muundo mmoja kwa mfumo mzima (E.164): "+" + code ya nchi + namba.

Tanzania (PHONE_COUNTRY_CODE, kawaida 255) - inakubali njia yoyote ya kawaida:
    0712 345 678 | 712345678 | 255712345678 | +255 712-345-678 | 00255712345678  ->  +255712345678
Nchi nyingine (kimataifa) - code ya nchi + namba, na "+" au "00" au bila:
    +86 138 1234 5678 | 008613812345678 | 8613812345678   ->  +8613812345678
    +254 712 345 678 (Kenya), +256 ..., +971 ..., +1 ...

Namba si lazima: tupu -> None. Namba isiyo sahihi -> BadRequest (ujumbe unaeleza muundo).
"""
import logging
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import config
from .exceptions import BadRequest

logger = logging.getLogger(__name__)

NATIONAL_DIGITS = 9
# E.164: tarakimu 8 hadi 15 (bila "+"), ya kwanza si 0
INTL_MIN_DIGITS = 8
INTL_MAX_DIGITS = 15


def country_code() -> str:
    return re.sub(r"\D", "", config.PHONE_COUNTRY_CODE or "255") or "255"


def example() -> str:
    return f"+{country_code()}712345678"


def error_message(raw: str | None = None) -> str:
    shown = f" ({raw.strip()})" if raw and raw.strip() else ""
    return (f"Namba ya simu si sahihi{shown}. Tanzania: {example()} au 0712345678; nchi nyingine: "
            f"+code ya nchi na namba, mf. +8613812345678 / Invalid phone number: use {example()} "
            f"or an international number with its country code, e.g. +8613812345678")


def try_normalize(raw: str | None) -> str | None:
    """+255XXXXXXXXX (Tanzania) au +<code><namba> (kimataifa); None kama ni tupu au si sahihi - haitoi kosa."""
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    international = value.startswith("+") or digits.startswith("00")
    if digits.startswith("00"):
        digits = digits[2:]
    cc = country_code()

    # 1. Tanzania (nchi ya mfumo)
    national = None
    if digits.startswith(cc) and len(digits) == len(cc) + NATIONAL_DIGITS:
        national = digits[len(cc):]
    elif not international and digits.startswith("0") and len(digits) == NATIONAL_DIGITS + 1:
        national = digits[1:]
    elif not international and len(digits) == NATIONAL_DIGITS:
        national = digits
    if national is not None:
        return f"+{cc}{national}" if re.fullmatch(r"[1-9]\d{8}", national) else None

    # 2. Nchi nyingine: code ya nchi + namba (E.164). "+255..." yenye urefu usio sahihi haikubaliki.
    if digits.startswith(cc) or digits.startswith("0"):
        return None
    if not international and len(digits) < 10:  # tarakimu chache bila "+" -> haijulikani ni ya nchi gani
        return None
    if INTL_MIN_DIGITS <= len(digits) <= INTL_MAX_DIGITS:
        return f"+{digits}"
    return None


def is_local(phone: str | None) -> bool:
    """Kama namba (iliyokwisha kusafishwa) ni ya Tanzania / nchi ya mfumo."""
    return bool(phone) and phone.startswith(f"+{country_code()}")


def normalize(raw: str | None, required: bool = False, label: str = "Namba ya simu") -> str | None:
    """Kwa data inayoingizwa: tupu -> None (au kosa kama `required`), si sahihi -> BadRequest."""
    if raw is None or not str(raw).strip():
        if required:
            raise BadRequest(f"{label} inahitajika / phone number is required")
        return None
    phone = try_normalize(raw)
    if phone is None:
        raise BadRequest(error_message(str(raw)))
    return phone


def search_digits(text_: str | None) -> str:
    """Tarakimu za kutafuta namba bila kujali muundo (0712.. / 255712.. / +255712..) -> '712..'."""
    digits = re.sub(r"\D", "", text_ or "")
    cc = country_code()
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith(cc) and len(digits) > len(cc) + 2:
        digits = digits[len(cc):]
    elif digits.startswith("0"):
        digits = digits[1:]
    return digits


def for_gateway(phone: str | None) -> str | None:
    """Namba inayotumwa kwa gateway ya SMS: +255XXXXXXXXX (au bila + kama SMS_MSISDN_PLUS=false)."""
    p = try_normalize(phone)
    if p is None:
        return None
    return p if config.SMS_MSISDN_PLUS else p[1:]


# ---------------------------------------------------------------- data ya zamani
# (table, column, unique?) - namba zilizohifadhiwa kabla ya muundo huu zinabadilishwa zenyewe wakati wa kuanza.
_COLUMNS = [
    ("customers", "phoneNumber", True),
    ("users", "phoneNumber", True),
    ("receivers", "phoneNumber", False),
    ("handovers", "collectorPhone", False),
    ("offices", "phoneNumber", False),
]


def migrate_existing(db: Session) -> dict:
    """Inabadilisha namba za zamani kuwa +<code><namba> (salama kurudiwa). Tupu -> NULL."""
    changed = skipped = 0
    cc = country_code()
    clean = r"^\+[1-9][0-9]{7,14}$"  # tayari ziko kwenye muundo sahihi - haziguswi
    for table, column, unique in _COLUMNS:
        try:
            rows = db.execute(text(f'SELECT id, "{column}" FROM "{table}" '
                                   f'WHERE "{column}" IS NOT NULL AND "{column}" !~ :p'),
                              {"p": clean}).all()
        except Exception:  # table haipo bado
            db.rollback()
            continue
        taken = set()
        if unique and rows:
            taken = {r[0] for r in db.execute(text(f'SELECT "{column}" FROM "{table}" WHERE "{column}" ~ :p'),
                                              {"p": clean}).all()}
        for row_id, raw in rows:
            if raw is None or not str(raw).strip():
                db.execute(text(f'UPDATE "{table}" SET "{column}" = NULL WHERE id = :id'), {"id": row_id})
                changed += 1
                continue
            phone = try_normalize(raw)
            if phone is None or (unique and phone in taken):
                skipped += 1
                logger.warning("Namba haikubadilishwa %s.%s %s: %r", table, column, row_id, raw)
                continue
            taken.add(phone)
            db.execute(text(f'UPDATE "{table}" SET "{column}" = :v WHERE id = :id'), {"v": phone, "id": row_id})
            changed += 1
    # SMS ambazo bado hazijatumwa
    for sid, raw in db.execute(text('SELECT id, msisdn FROM sms WHERE "isSMSSend" = false AND msisdn !~ :p'),
                               {"p": clean}).all():
        phone = try_normalize(raw)
        if phone:
            db.execute(text("UPDATE sms SET msisdn = :v WHERE id = :id"), {"v": phone, "id": sid})
            changed += 1
    db.commit()
    if changed or skipped:
        logger.info("Namba za simu: %s zimebadilishwa kuwa +%s..., %s hazikuweza", changed, cc, skipped)
    return {"changed": changed, "skipped": skipped}
