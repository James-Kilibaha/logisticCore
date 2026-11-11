"""
Ripoti za kufika kwa ujumbe (delivery reports, DLR).

- SMS (FastHub): gateway inaita `/api/public/sms-dlr/<SMS_DLR_TOKEN>` (GET au POST; JSON, form au query).
  Tunakubali majina ya kawaida ya sehemu (reference/msgid/id, status/dlr/state, description/error), moja au orodha.
- WhatsApp (Meta): webhook `/api/public/whatsapp/webhook` - `statuses` (sent / delivered / read / failed).

Hali zinazohifadhiwa kwenye Sms.deliveryStatus: SENT (gateway imepokea), DELIVERED (imefika), FAILED (haikufika).
"""
import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..core.base_model import utc_now
from .model import Sms

logger = logging.getLogger(__name__)

REF_KEYS = ("reference", "ref", "clientReference", "client_reference", "clientRef", "msgid", "msgId", "messageId",
            "message_id", "smsId", "sms_id", "id")
STATUS_KEYS = ("status", "dlr", "dlrStatus", "dlr_status", "deliveryStatus", "delivery_status", "state", "stat")
NOTE_KEYS = ("description", "statusDescription", "status_description", "error", "errorDescription", "reason", "err")

_DELIVERED = ("DELIVRD", "DELIVERED", "SUCCESS", "READ")
_FAILED = ("UNDELIV", "FAIL", "REJECT", "EXPIRED", "ERROR", "INVALID", "BLACKLIST", "BLOCKED", "DELETED", "UNKNOWN")
_SENT = ("ACCEPT", "ENROUTE", "SENT", "SUBMIT", "PENDING", "BUFFERED", "QUEUED")


def normalise(status) -> str | None:
    s = str(status or "").strip().upper()
    if not s:
        return None
    if any(k in s for k in _FAILED):
        return "FAILED"
    if any(k in s for k in _DELIVERED):
        return "DELIVERED"
    if any(k in s for k in _SENT):
        return "SENT"
    return None


def _first(d: dict, keys) -> str | None:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return None


def _records(payload) -> list[dict]:
    """Payload inaweza kuwa ripoti moja, orodha, au {"data"/"results"/"messages"/"reports": [...]}."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "messages", "reports", "dlr"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
            if isinstance(inner, dict) and _first(inner, REF_KEYS):
                return [inner]
        return [payload]
    return []


def gateway_message_id(body) -> str | None:
    """Id ya ujumbe kwenye jibu la gateway wakati wa kutuma (kama ipo)."""
    for rec in _records(body):
        for k in ("messageId", "message_id", "msgid", "msgId", "id"):
            v = rec.get(k)
            if v not in (None, "") and not isinstance(v, (dict, list, bool)):
                return str(v)
    return None


def _apply(db: Session, ref: str, status: str, note: str | None) -> bool:
    sms = db.query(Sms).filter(or_(Sms.gatewayRef == ref, Sms.gatewayId == ref)).first()
    if sms is None:
        return False
    if sms.deliveryStatus == "DELIVERED" and status != "DELIVERED":
        return True  # ripoti ya zamani iliyochelewa haiondoi "imefika"
    sms.deliveryStatus = status
    if status == "DELIVERED":
        sms.deliveredAt = utc_now()
        sms.error = None
    elif status == "FAILED":
        sms.error = (note or "Haikufika kwa mteja")[:300]
    return True


def apply_reports(db: Session, payload) -> dict:
    """Inasasisha hali ya ujumbe kutoka kwenye ripoti(za) za gateway. Inarudisha idadi zilizotambuliwa."""
    matched = unknown = ignored = 0
    for rec in _records(payload):
        ref = _first(rec, REF_KEYS)
        status = normalise(_first(rec, STATUS_KEYS))
        if not ref or status is None:
            ignored += 1
            continue
        if _apply(db, ref, status, _first(rec, NOTE_KEYS)):
            matched += 1
        else:
            unknown += 1
    db.commit()
    if unknown or ignored:
        logger.info("DLR: matched %s, unknown %s, ignored %s", matched, unknown, ignored)
    return {"matched": matched, "unknown": unknown, "ignored": ignored}


def apply_whatsapp(db: Session, payload: dict) -> dict:
    """Meta webhook: entry[].changes[].value.statuses[] {id, status, errors}."""
    reports = []
    for entry in (payload or {}).get("entry") or []:
        for change in entry.get("changes") or []:
            for st in (change.get("value") or {}).get("statuses") or []:
                errors = st.get("errors") or [{}]
                reports.append({"id": st.get("id"), "status": st.get("status"),
                                "error": errors[0].get("title") or errors[0].get("message")})
    return apply_reports(db, reports)


def summary(db: Session, since) -> dict:
    """Idadi kwa hali (kwa SMS zilizotumwa tangu `since`)."""
    from sqlalchemy import func

    rows = (db.query(Sms.channel, Sms.deliveryStatus, func.count(Sms.id))
            .filter(Sms.isSMSSend.is_(True), Sms.created_at >= since)
            .group_by(Sms.channel, Sms.deliveryStatus).all())
    out: dict[str, dict[str, int]] = {}
    for channel, status, n in rows:
        out.setdefault(channel or "SMS", {})[status or "UNKNOWN"] = n
    return out
