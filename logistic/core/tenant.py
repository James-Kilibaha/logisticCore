"""
Multi-tenant: kila kampuni ya usafirishaji (mteja wa mfumo) ina data yake peke yake.

Kila request inapata "tenant" yake (kampuni) mapema kwenye `TenantMiddleware` (saas/middleware.py):
  1. token ya mtumiaji (claim `cid`)
  2. header `X-Company: <slug>` (app ya simu)
  3. domain iliyofungua app (`ymg.co.tz`, `ymg.<PLATFORM_DOMAIN>`)

Baada ya hapo, kila query ya ORM kwenye table yoyote inayorithi `EntityBase` inachujwa yenyewe kwa
`company_id` ya kampuni hiyo, na kila rekodi mpya inaandikwa `company_id` yake (tazama `db.py`).
Kwa hiyo dao/service za zamani hazihitaji kubadilishwa.

Hali (mode):
  - "tenant"  : data ya kampuni moja tu. company_id=None = hakuna kitu kinachorudishwa (fail closed).
  - "system"  : hakuna kuchuja (scheduler, startup, webhooks, platform admin).
"""
import contextvars
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class TenantState:
    mode: str = "system"
    company_id: uuid.UUID | None = None
    slug: str | None = None


_state: contextvars.ContextVar[TenantState] = contextvars.ContextVar("tenant_state", default=TenantState())


def state() -> TenantState:
    return _state.get()


def company_id() -> uuid.UUID | None:
    s = _state.get()
    return s.company_id if s.mode == "tenant" else None


def is_tenant() -> bool:
    return _state.get().mode == "tenant"


def require_company_id() -> uuid.UUID:
    cid = company_id()
    if cid is None:
        from .exceptions import BadRequest

        raise BadRequest("Kampuni haijulikani / company not specified")
    return cid


def set_state(new: TenantState):
    """Inarudisha token ya kurudisha hali ya awali (`reset`)."""
    return _state.set(new)


def reset(token) -> None:
    _state.reset(token)


@contextmanager
def use_company(cid, slug: str | None = None):
    """Kazi zisizo za request (scheduler, seed) zinazofanya kazi kwa kampuni moja."""
    if cid is not None and not isinstance(cid, uuid.UUID):
        cid = uuid.UUID(str(cid))
    token = _state.set(TenantState(mode="tenant", company_id=cid, slug=slug))
    try:
        yield
    finally:
        _state.reset(token)


@contextmanager
def system():
    """Bila kuchuja (kuona kampuni zote)."""
    token = _state.set(TenantState(mode="system"))
    try:
        yield
    finally:
        _state.reset(token)


def spawn(target, *args) -> threading.Thread:
    """Thread mpya inayobeba kampuni ya sasa (threading.Thread peke yake haibebi contextvars)."""
    ctx = contextvars.copy_context()
    thread = threading.Thread(target=ctx.run, args=(target, *args), daemon=True)
    thread.start()
    return thread


def active_company_ids() -> list[tuple[uuid.UUID, str]]:
    """Kampuni zote zisizozuiwa (kwa kazi za scheduler)."""
    from ..db import SessionLocal
    from ..saas.company.model import Company

    with system():
        db = SessionLocal()
        try:
            rows = db.query(Company.id, Company.slug).filter(Company.status == "ACTIVE").all()
        finally:
            db.close()
    return [(r[0], r[1]) for r in rows]


def for_each_company(job):
    """Inageuza kazi ya kampuni moja kuwa kazi inayoendeshwa kwa kila kampuni (scheduler)."""
    import logging

    log = logging.getLogger(__name__)

    def run():
        errors = []
        for cid, slug in active_company_ids():
            try:
                with use_company(cid, slug):
                    job()
            except Exception as error:  # kampuni moja ikishindwa, nyingine ziendelee
                log.exception("Job %s failed for company %s", getattr(job, "__name__", job), slug)
                errors.append(f"{slug}: {error}")
        if errors:
            raise RuntimeError("; ".join(errors)[:300])

    run.__name__ = getattr(job, "__name__", "job")
    return run
