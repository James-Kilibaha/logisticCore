"""
Ufuatiliaji wa server: hali ya database, diski, backup, SMS/WhatsApp na kazi za scheduler.
Kila saa `check_and_alert()` inakagua na kutuma tahadhari (taarifa ndani ya app + SMS/email kwa
ALERT_PHONES / ALERT_EMAILS) - kila tatizo mara moja kwa saa 12.
"""
import logging
import secrets
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

from .. import config
from .base_model import utc_now

logger = logging.getLogger(__name__)
STARTED = time.time()
VERSION = "2.8.0"


def _disk(path: Path) -> dict:
    try:
        path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(path)
        return {"path": str(path), "freeGb": round(usage.free / 1e9, 2), "totalGb": round(usage.total / 1e9, 2),
                "usedPct": round(usage.used / usage.total * 100, 1) if usage.total else 0}
    except OSError as error:
        return {"path": str(path), "error": str(error)}


def details() -> dict:
    from ..db import SessionLocal
    from ..sms.model import Sms
    from . import scheduler, whatsapp

    out: dict = {"version": VERSION, "env": config.APP_ENV, "uptimeHours": round((time.time() - STARTED) / 3600, 1),
                 "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    db = SessionLocal()
    try:
        t0 = time.perf_counter()
        db.execute(text("SELECT 1"))
        out["database"] = {"ok": True, "latencyMs": round((time.perf_counter() - t0) * 1000, 1)}
        since = utc_now() - timedelta(hours=6)
        out["sms"] = {
            "configured": bool(config.SMS_CLIENT_ID and config.SMS_CLIENT_SECRET),
            "autoSend": config.SMS_AUTO_SEND,
            "pending": db.query(Sms).filter(Sms.isSMSSend.is_(False)).count(),
            "stuck": db.query(Sms).filter(Sms.isSMSSend.is_(False), Sms.created_at < since,
                                          Sms.created_at > utc_now() - timedelta(days=3)).count(),
            "failing": db.query(Sms).filter(Sms.isSMSSend.is_(False), Sms.error.isnot(None)).count(),
            "notDelivered24h": db.query(Sms).filter(Sms.deliveryStatus == "FAILED",
                                                    Sms.sentAt > utc_now() - timedelta(hours=24)).count(),
        }
        from ..sms.credit import status as credit_status

        c = credit_status(db)
        out["sms"].update(balance=c["balance"], balanceSource=c["source"], lowBalance=c["low"])
    except Exception as error:
        out["database"] = {"ok": False, "error": str(error)[:200]}
    finally:
        db.close()
    out["whatsapp"] = {"configured": whatsapp.configured(), "enabled": config.WHATSAPP_ENABLED}
    out["disk"] = {"files": _disk(config.FILES_DIR), "backup": _disk(config.BACKUP_DIR)}
    try:
        from ..backup.service import status as backup_status

        b = backup_status()
        last = b.get("last")
        age = None
        if last:
            created = datetime.fromisoformat(last["created_at"])
            age = round((datetime.now(timezone.utc) - created).total_seconds() / 3600, 1)
        out["backup"] = {**b, "ageHours": age}
    except Exception as error:
        out["backup"] = {"error": str(error)[:200]}
    out["jobs"] = scheduler.jobs()
    out["scheduler"] = scheduler.leader_status()  # leader = worker huyu ndiye anaendesha kazi
    out["problems"] = problems(out)
    return out


def problems(d: dict) -> list[dict]:
    """Orodha ya matatizo: [{key, message}]"""
    found = []
    if not d.get("database", {}).get("ok", False):
        found.append({"key": "db", "message": f"Database haipatikani: {d['database'].get('error', '')}"})
    for name, disk in d.get("disk", {}).items():
        if disk.get("freeGb") is not None and disk["freeGb"] < config.ALERT_DISK_MIN_GB:
            found.append({"key": f"disk-{name}", "message": f"Nafasi ya diski ({name}) imebaki {disk['freeGb']} GB"})
    backup = d.get("backup", {})
    if backup.get("enabled"):
        age = backup.get("ageHours")
        if age is None:
            found.append({"key": "backup-none", "message": "Hakuna backup yoyote bado"})
        elif age > config.ALERT_BACKUP_MAX_HOURS:
            found.append({"key": "backup-old", "message": f"Backup ya mwisho ni ya saa {age:.0f} zilizopita"})
    sms = d.get("sms", {})
    if sms.get("autoSend") and sms.get("stuck", 0) >= 10:
        found.append({"key": "sms-stuck", "message": f"SMS {sms['stuck']} hazijatumwa kwa zaidi ya saa 6"})
    if sms.get("lowBalance"):
        found.append({"key": "sms-balance", "message": f"Salio la SMS limebaki {int(sms['balance']):,}"})
    for job in d.get("jobs", []):
        if job.get("lastError"):
            found.append({"key": f"job-{job['id']}", "message": f"Kazi '{job['id']}' imeshindwa: {job['lastError']}"})
    return found


def _send_sms(phone: str, message: str) -> None:
    import requests

    if not (config.SMS_CLIENT_ID and config.SMS_CLIENT_SECRET):
        return
    payload = {"auth": {"clientId": config.SMS_CLIENT_ID, "clientSecret": config.SMS_CLIENT_SECRET},
               "messages": [{"text": message[:459], "msisdn": phone, "source": config.SMS_SOURCE_NAME,
                             "reference": f"ALERT{secrets.token_hex(12).upper()}", "coding": config.SMS_CODING}]}
    try:
        from ..sms.service import GATEWAY_HEADERS, gateway_url

        requests.post(gateway_url(config.SMS_API), json=payload, timeout=20, headers=GATEWAY_HEADERS,
                      allow_redirects=False)
    except Exception:
        logger.exception("Alert SMS failed")


def _send_email(subject: str, body: str) -> None:
    from . import mail

    mail.send(config.ALERT_EMAILS, subject, body)


def alert(items: list[dict], force: bool = False) -> int:
    """Inatuma tahadhari mpya (kila key mara moja kwa saa 12, isipokuwa force)."""
    from ..db import SessionLocal
    from ..notification.service import notify

    db = SessionLocal()
    sent = []
    sms_on = True
    try:
        from ..core.enums import ESmsStatus
        from ..sms.service import kind_enabled

        sms_on = kind_enabled(db, ESmsStatus.ALERT)
        for item in items:
            n = notify(db, "SETTING", "update", kind="ALERT", title="⚠️ " + item["message"][:180],
                       body=config.COMPANY_NAME, link=f"alert:{item['key']}", dedupe_hours=None if force else 12)
            if n or force:
                sent.append(item["message"])
        db.commit()
    finally:
        db.close()
    if sent:
        text_ = f"{config.COMPANY_NAME} - TAHADHARI: " + " | ".join(sent)
        for phone in config.ALERT_PHONES if sms_on else []:
            _send_sms(phone, text_)
        _send_email(f"[{config.COMPANY_NAME}] Tahadhari ya mfumo", "\n".join(f"- {m}" for m in sent))
    return len(sent)


def check_and_alert() -> int:
    found = problems(details())
    if found:
        from ..saas.notice.service import notify

        for item in found:
            notify("SYSTEM", "SYSTEM", "⚠️ " + item["message"][:180], link="system", urgent=True,
                   dedupe=f"system:{item['key']}", dedupe_hours=6)
    return alert(found) if found else 0
