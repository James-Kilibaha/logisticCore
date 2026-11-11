"""
Salio la SMS na onyo likikaribia kuisha.

Njia mbili (zinaweza kutumika pamoja):
1. Makadirio ya ndani: msimamizi anarekodi salio halisi (SET) au SMS alizonunua (ADD); mfumo unatoa vipande vya
   kila SMS iliyotumwa baada ya hapo (Sms.parts).
2. Gateway: kama SMS_BALANCE_API imewekwa, salio linaulizwa moja kwa moja kutoka FastHub.
Salio likishuka chini ya SMS_LOW_BALANCE, wenye ruhusa ya SMS wanapata taarifa (mara moja kwa siku).
"""
import logging

import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import config
from ..core.exceptions import BadRequest
from .model import Sms, SmsCredit

logger = logging.getLogger(__name__)
KINDS = ("SET", "ADD")


def record(db: Session, kind: str, amount: int, note: str | None, user_id) -> SmsCredit:
    kind = (kind or "").upper()
    if kind not in KINDS:
        raise BadRequest("kind must be SET or ADD")
    if amount < 0 or (kind == "ADD" and amount == 0):
        raise BadRequest("Weka idadi sahihi ya SMS")
    row = SmsCredit(kind=kind, amount=int(amount), note=(note or "").strip()[:200] or None, logsId=user_id)
    db.add(row)
    db.commit()
    return row


def _number(body) -> float | None:
    """Salio kutoka kwenye jibu la gateway: balance / credit / credits / sms_balance (pia ndani ya data)."""
    if isinstance(body, (int, float)) and not isinstance(body, bool):
        return float(body)
    if isinstance(body, dict):
        for k in ("balance", "sms_balance", "smsBalance", "credit", "credits", "units"):
            v = body.get(k)
            try:
                if v is not None and not isinstance(v, bool):
                    return float(str(v).replace(",", ""))
            except ValueError:
                pass
        for k in ("data", "result", "account"):
            n = _number(body.get(k))
            if n is not None:
                return n
    return None


# Salio la mwisho ambalo FastHub ilirudisha kwenye jibu la kutuma SMS ({"balance": ...}), kwa kila AKAUNTI:
# "platform" = akaunti yako ya .env (kampuni zisizo na FastHub yao zinaitumia), au id ya kampuni yenye akaunti yake.
_LAST_GATEWAY: dict[str, dict] = {}


def account_key() -> str:
    """Akaunti ya SMS inayotumika sasa: ya kampuni yenyewe (id yake) au yako ("platform")."""
    from ..core import tenant

    cid = tenant.company_id()
    if cid is None:
        return "platform"
    from ..saas.company import settings as company_settings

    return str(cid) if company_settings.value(cid, "_OWN_SMS") else "platform"


def own_account() -> bool:
    """Kampuni ina akaunti yake ya FastHub - salio lake linaweza kuonyeshwa kwake."""
    return account_key() != "platform"


def remember_gateway_balance(value: float) -> None:
    from ..core.base_model import utc_now

    _LAST_GATEWAY[account_key()] = {"value": float(value), "at": utc_now()}


def platform_balance() -> tuple[float | None, str | None]:
    """Salio la akaunti yako (kwa admin panel)."""
    mem = _LAST_GATEWAY.get("platform") or {}
    return mem.get("value"), mem["at"].isoformat(timespec="seconds") if mem.get("at") else None


def last_gateway_balance(db: Session | None = None) -> tuple[float | None, str | None]:
    """
    Salio la mwisho ambalo FastHub ilirudisha: la karibuni kati ya kumbukumbu (pamoja na SMS za muda kama OTP)
    na SMS iliyohifadhiwa (Sms.balanceAfter) - kwa hiyo halipotei backend ikiwashwa upya.
    Kampuni inayotumia akaunti yako haioni salio (ni lako, si lake).
    """
    from ..core import tenant

    if tenant.company_id() is not None and not own_account():
        return None, None
    mem = _LAST_GATEWAY.get(account_key()) or {}
    value, at = mem.get("value"), mem.get("at")
    if db is not None and tenant.company_id() is not None:
        row = (db.query(Sms.balanceAfter, Sms.sentAt)
               .filter(Sms.balanceAfter.isnot(None), Sms.sentAt.isnot(None))
               .order_by(Sms.sentAt.desc()).first())
        if row is not None and (at is None or row.sentAt > at):
            value, at = row.balanceAfter, row.sentAt
    if at is None:
        return None, None
    return value, at.isoformat(timespec="seconds")


def gateway_balance() -> float | None:
    if not (config.SMS_BALANCE_API and config.SMS_CLIENT_ID and config.SMS_CLIENT_SECRET):
        return None
    try:
        from .service import GATEWAY_HEADERS

        r = requests.post(config.SMS_BALANCE_API, timeout=15, headers=GATEWAY_HEADERS,
                          json={"auth": {"clientId": config.SMS_CLIENT_ID, "clientSecret": config.SMS_CLIENT_SECRET}})
        if r.status_code != 200:
            logger.warning("SMS balance API status %s: %s", r.status_code, r.text[:200])
            return None
        return _number(r.json())
    except (requests.RequestException, ValueError) as error:
        logger.warning("SMS balance API failed: %s", error)
        return None


def estimate(db: Session) -> dict:
    base = db.query(SmsCredit).filter(SmsCredit.kind == "SET").order_by(SmsCredit.created_at.desc()).first()
    q_add = db.query(func.coalesce(func.sum(SmsCredit.amount), 0)).filter(SmsCredit.kind == "ADD")
    q_used = db.query(func.coalesce(func.sum(Sms.parts), 0)).filter(Sms.channel == "SMS", Sms.sentAt.isnot(None))
    if base is not None:
        q_add = q_add.filter(SmsCredit.created_at > base.created_at)
        q_used = q_used.filter(Sms.sentAt > base.created_at)
    added, used = int(q_add.scalar() or 0), int(q_used.scalar() or 0)
    tracked = base is not None or added > 0
    return {"tracked": tracked, "base": base.amount if base else 0,
            "baseAt": base.created_at.isoformat() if base and base.created_at else None,
            "added": added, "used": used,
            "estimated": (base.amount if base else 0) + added - used if tracked else None}


def status(db: Session, ask_gateway: bool = True) -> dict:
    est = estimate(db)
    gateway = gateway_balance() if ask_gateway else None
    seen_at = None
    if gateway is None:  # salio lililorudishwa na FastHub SMS ilipotumwa mara ya mwisho
        gateway, seen_at = last_gateway_balance(db)
    balance = gateway if gateway is not None else est["estimated"]
    month_used = int(db.query(func.coalesce(func.sum(Sms.parts), 0))
                     .filter(Sms.channel == "SMS", Sms.sentAt >= _month_start()).scalar() or 0)
    history = [{"id": str(c.id), "kind": c.kind, "amount": c.amount, "note": c.note,
                "created_at": c.created_at.isoformat() if c.created_at else None}
               for c in db.query(SmsCredit).order_by(SmsCredit.created_at.desc()).limit(10)]
    return {"balance": balance, "source": "GATEWAY" if gateway is not None else ("ESTIMATE" if est["tracked"] else None),
            "gateway": gateway, "gatewaySeenAt": seen_at, **est, "usedThisMonth": month_used, "lowAt": config.SMS_LOW_BALANCE,
            "low": balance is not None and balance < config.SMS_LOW_BALANCE, "history": history}


def _month_start():
    from ..core.base_model import utc_now

    now = utc_now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def alert_low() -> None:
    """Scheduler: taarifa kwa wenye ruhusa ya SMS salio likiwa chini (mara moja kwa saa 20)."""
    from ..db import session_scope
    from ..notification.service import notify

    with session_scope() as db:
        s = status(db)
        if not s["low"]:
            return
        notify(db, "SMS", "select", kind="SMS_LOW_BALANCE", title=f"Salio la SMS limebaki {int(s['balance']):,}",
               body=f"Ongeza salio la FastHub kabla SMS hazijasimama (onyo chini ya {config.SMS_LOW_BALANCE:,}).",
               link="sms", dedupe_hours=20)
        db.commit()
