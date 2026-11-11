"""
Kazi zinazojiendesha zenyewe (kazi za kampuni zinaendeshwa kwa kila kampuni - tenant.for_each_company):
- kila saa 2 : kuongeza siku za stoo kwa mizigo iliyokaa zaidi ya DAYS_TO_CHARGE
- kila siku : backup ya database + mafaili (saa BACKUP_HOUR)
- kila saa 6 : taarifa ya mizigo iliyokaa stoo zaidi ya siku za bure (inarudiwa kila STORAGE_ALERT_EVERY_DAYS)
- kila saa 6 : onyo la salio la SMS likiwa chini ya SMS_LOW_BALANCE
- kila saa 6 : kufuta picha za bidhaa za invoice zilizokamilika na kulipwa (baada ya IMAGE_RETENTION_DAYS)
"""
import logging
import os
import threading
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from .. import config
from ..db import session_scope
from . import files, tenant
from .base_model import utc_now
from .enums import EInvoiceStatus

logger = logging.getLogger(__name__)


def charge_storage_days() -> None:
    """Inasasisha siku na gharama za stoo kwa kila mzigo ulio stoo (tazama payment/storage.py)."""
    from ..invoice.model import Invoice
    from ..payment import storage
    from ..payment.dao import DebtDao

    with session_scope() as db:
        invoices = db.query(Invoice).filter(Invoice.status == EInvoiceStatus.STORE.name).all()
        if not invoices:
            return
        debts = {d.invoice_id: d for d in DebtDao(db).for_invoices([i.id for i in invoices], before=utc_now())}
        for invoice in invoices:
            storage.refresh(db, invoice, debts.get(invoice.id))
        db.commit()


def remove_old_images() -> None:
    """
    Picha za mizigo zinafutwa siku PHOTO_DELETE_AFTER_HANDOVER_DAYS (kawaida 3) baada ya mteja kukabidhiwa
    mzigo na kusaini. Picha zinazosubiri usajili (QR ya simu) zinafutwa baada ya saa 24.
    (Sahihi na picha ya makabidhiano hazifutwi: ni ushahidi wa kukabidhi.) Inaendeshwa kwa kila kampuni.
    """
    from sqlalchemy import func

    from ..handover.model import Handover
    from ..invoice.model import Invoice
    from ..product.model import Product
    from ..product.photo import cleanup_staged

    cleanup_staged()
    with session_scope() as db:
        cutoff = utc_now() - timedelta(days=max(config.PHOTO_DELETE_AFTER_HANDOVER_DAYS, 0))
        handed = (db.query(Handover.invoice_id, func.max(Handover.created_at).label("at"))
                  .group_by(Handover.invoice_id).subquery())
        products = (db.query(Product)
                    .join(Invoice, Product.invoice_id == Invoice.id)
                    .join(handed, handed.c.invoice_id == Invoice.id)
                    .filter(Invoice.status.in_([EInvoiceStatus.COMPLETED.name, EInvoiceStatus.DELIVERED.name]),
                            handed.c.at < cutoff, Product.path.isnot(None))
                    .all())
        for product in products:
            try:
                if files.remove(product.path):
                    product.path = None
            except OSError:
                logger.exception("Could not delete image %s", product.path)
        db.commit()


# Hali ya kazi za scheduler (inaonekana kwenye /api/health/details na kwenye tahadhari)
JOB_STATE: dict[str, dict] = {}
_scheduler = None  # _Handle (tazama start)


def _safe(job):
    def run():
        state = JOB_STATE.setdefault(job.__name__, {})
        try:
            job()
            state.update(lastRun=utc_now().isoformat(timespec="seconds"), lastError=None)
        except Exception as error:
            logger.exception("Scheduled job %s failed", job.__name__)
            state.update(lastRun=utc_now().isoformat(timespec="seconds"), lastError=str(error)[:300],
                         failedAt=utc_now().isoformat(timespec="seconds"))
    run.__name__ = job.__name__
    return run


def jobs() -> list[dict]:
    out = []
    if _scheduler is None:
        return out
    for job in _scheduler.get_jobs():
        state = JOB_STATE.get(job.id.replace("daily_backup", "scheduled_backup"), {}) or JOB_STATE.get(job.id, {})
        out.append({"id": job.id, "next": job.next_run_time.isoformat(timespec="seconds") if job.next_run_time else None,
                    **{k: v for k, v in state.items()}})
    return out


def _if_reminders_enabled(job):
    def run():
        if config.REMINDERS_ENABLED:  # mpangilio wa kampuni hii
            job()

    run.__name__ = job.__name__
    return run


# ------------------------------------------------------------------ worker mmoja tu anaendesha kazi
# Backend ikiendeshwa na workers wengi (uvicorn --workers N au server zaidi ya moja), kila mmoja angeendesha
# kazi hizi - wateja wangepata SMS mara mbili. PostgreSQL advisory lock inahakikisha ni mmoja tu ("leader");
# wengine wanasubiri na kuchukua nafasi leader akizima.
LEADER_LOCK_KEY = 0x4C4F4749  # "LOGI"
_LEADER: dict = {"conn": None, "since": None, "role": "none"}


def _try_lead() -> bool:
    from ..db import engine

    conn = engine.raw_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LEADER_LOCK_KEY,))
        ok = bool(cur.fetchone()[0])
        conn.commit()
    except Exception:
        conn.close()
        raise
    if not ok:
        conn.close()
        return False
    conn.detach()  # connection ya peke yake (si ya pool): lock inadumu mpaka process hii izime
    _LEADER.update(conn=conn, since=utc_now(), role="leader")
    return True


def _leader_alive() -> bool:
    conn = _LEADER.get("conn")
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        conn.commit()
        return True
    except Exception:
        return False


def leader_status() -> dict:
    since = _LEADER.get("since")
    return {"role": _LEADER.get("role"), "since": since.isoformat(timespec="seconds") if since else None,
            "pid": os.getpid()}


class _Handle:
    """Inarudishwa na start(): leader -> scheduler halisi; follower -> inajaribu kuwa leader kila dakika."""

    def __init__(self):
        self.scheduler: BackgroundScheduler | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def begin(self) -> None:
        try:
            lead = _try_lead()
        except Exception:
            logger.exception("Scheduler: leader lock check failed - kazi zinaendeshwa hapa (bila lock)")
            _LEADER.update(role="unlocked", since=utc_now())
            lead = True
        if lead:
            self._run()
        else:
            _LEADER.update(role="follower", since=utc_now())
            logger.info("Scheduler: worker mwingine anaendesha kazi - huyu (pid %s) anasubiri", os.getpid())
        self._thread = threading.Thread(target=self._watch, name="scheduler-leader", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        if self.scheduler is None:
            self.scheduler = _build()
            self.scheduler.start()
            logger.info("Scheduler: worker huyu (pid %s) ndiye anaendesha kazi", os.getpid())

    def _watch(self) -> None:
        while not self._stop.wait(60):
            try:
                if self.scheduler is not None:
                    if _LEADER.get("role") == "leader" and not _leader_alive():
                        # connection ya lock imekatika: acha kazi (worker mwingine atachukua lock)
                        logger.warning("Scheduler: lock imepotea - kazi zinasimamishwa kwenye pid %s", os.getpid())
                        self.scheduler.shutdown(wait=False)
                        self.scheduler = None
                        _LEADER.update(conn=None, role="follower", since=utc_now())
                elif _try_lead():
                    self._run()
            except Exception:
                logger.exception("Scheduler leader watch failed")

    def shutdown(self, wait: bool = False) -> None:
        self._stop.set()
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=wait)
        conn = _LEADER.get("conn")
        if conn is not None:
            try:
                conn.close()  # lock inaachiliwa
            except Exception:
                pass
        _LEADER.update(conn=None, role="none")

    def get_jobs(self):
        return self.scheduler.get_jobs() if self.scheduler is not None else []


def start() -> _Handle:
    global _scheduler
    handle = _Handle()
    _scheduler = handle
    handle.begin()
    return handle


def _build() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    each = tenant.for_each_company
    scheduler.add_job(_safe(each(charge_storage_days)), "interval", hours=2, id="charge_storage_days")
    scheduler.add_job(_safe(each(remove_old_images)), "interval", hours=6, id="remove_old_images")
    from ..sms.service import retry_recent_pending
    scheduler.add_job(_safe(each(retry_recent_pending)), "interval", minutes=15, id="retry_sms")
    from ..sms.credit import alert_low as sms_low_balance
    scheduler.add_job(_safe(each(sms_low_balance)), "interval", hours=6, id="sms_low_balance")
    from ..sms.reminders import scheduled as reminders
    # kila saa: kila aina ya SMS ya moja kwa moja ya kila kampuni inaendeshwa saa yake
    # (Mipangilio -> SMS za moja kwa moja); REMINDERS_ENABLED=false kwa kampuni = zimezimwa zote
    scheduler.add_job(_safe(each(_if_reminders_enabled(reminders))), "cron", minute=5, id="sms_reminders")
    if config.BACKUP_ENABLED:
        from ..backup.service import scheduled_backup
        scheduler.add_job(_safe(scheduled_backup), "cron", hour=config.BACKUP_HOUR, minute=0, id="daily_backup")
    from .monitor import check_and_alert
    from ..notification.service import cleanup as notifications_cleanup
    scheduler.add_job(_safe(check_and_alert), "interval", hours=1, id="monitor")
    from ..package.service import alert_late as late_boxes
    scheduler.add_job(_safe(each(late_boxes)), "cron", hour=8, minute=10, id="late_boxes_alert")
    from ..payment.storage import alert_overdue
    scheduler.add_job(_safe(each(alert_overdue)), "interval", hours=6, id="storage_overdue_alert")
    scheduler.add_job(_safe(each(notifications_cleanup)), "cron", hour=3, minute=30, id="notifications_cleanup")
    # SaaS: vikumbusho vya subscription kwa kampuni (kila siku asubuhi)
    from ..saas.subscription.service import remind_expiring
    scheduler.add_job(_safe(remind_expiring), "cron", hour=9, minute=20, id="subscription_reminders")
    # super admin: taarifa za kampuni zinazoisha + kusafisha taarifa za zamani
    from ..saas.notice.service import cleanup as notices_cleanup, scan_expiring
    scheduler.add_job(_safe(scan_expiring), "cron", hour=8, minute=40, id="platform_expiring_notices")
    scheduler.add_job(_safe(notices_cleanup), "cron", hour=3, minute=45, id="platform_notices_cleanup")
    from ..demand.service import scheduled as cost_demands

    # madai ya gharama: kumbusho saa ya kufunga kazi + taarifa ya kuzuia (kila saa, dakika 1) - kila kampuni
    scheduler.add_job(_safe(each(cost_demands)), "cron", minute=1, id="cost_demands")
    return scheduler
