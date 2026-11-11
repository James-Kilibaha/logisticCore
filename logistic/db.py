"""
Muunganiko na PostgreSQL.

- `engine`, `SessionLocal`, `Base`  : msingi wa SQLAlchemy
- `get_db()`                         : dependency ya FastAPI (session moja kwa kila request)
- `session_scope()`                  : session kwa kazi zisizo za request (scheduler, seed)
- `init_db()`                        : inaunda database (kama haipo) na tables zote
"""
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, event, false, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, declarative_base, sessionmaker, with_loader_criteria

from . import config

logger = logging.getLogger(__name__)


def database_url(database: str | None = None) -> URL:
    return URL.create(
        drivername="postgresql+psycopg2",
        username=config.DATABASE_USERNAME,
        password=config.DATABASE_PASSWORD,
        host=config.DATABASE_HOST,
        port=config.DATABASE_PORT,
        database=database or config.DATABASE_NAME,
    )


SQLALCHEMY_DATABASE_URL = database_url()

engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)

# expire_on_commit=False: vitu vinavyorudishwa kwa app havipotezi data baada ya commit nyingine.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

Base = declarative_base()


# --------------------------------------------------------------- multi-tenant
# Kila query ya ORM kwenye tables za kampuni (EntityBase) inachujwa kwa kampuni ya request hii,
# na kila rekodi mpya inapata company_id yake. Tazama core/tenant.py.

@event.listens_for(Session, "do_orm_execute")
def _tenant_filter(state):
    from .core import tenant
    from .core.base_model import EntityBase

    current = tenant.state()
    if current.mode != "tenant":
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    cid = current.company_id
    if cid is None:
        # Kampuni haijulikani: hakuna data inayorudishwa (fail closed)
        state.statement = state.statement.options(
            with_loader_criteria(EntityBase, lambda cls: false(), include_aliases=True))
        return
    state.statement = state.statement.options(
        with_loader_criteria(EntityBase, lambda cls: cls.company_id == cid, include_aliases=True))


def _stamp_insert(mapper, connection, target):
    """Kila rekodi mpya ya kampuni inapata company_id ya request (hata zilizoongezwa kwa cascade)."""
    from .core import tenant

    if getattr(target, "company_id", None) is None:
        target.company_id = tenant.company_id()


def register_tenant_events() -> None:
    from .core.base_model import EntityBase

    if not event.contains(EntityBase, "before_insert", _stamp_insert):
        event.listen(EntityBase, "before_insert", _stamp_insert, propagate=True)


@event.listens_for(Session, "before_flush")
def _tenant_stamp(session, flush_context, instances):
    from .core import tenant
    from .core.base_model import EntityBase

    cid = tenant.company_id()
    for obj in session.new:
        if isinstance(obj, EntityBase) and getattr(obj, "company_id", None) is None:
            if cid is None and tenant.is_tenant():
                from .core.exceptions import BadRequest

                raise BadRequest("Kampuni haijulikani / company not specified")
            obj.company_id = cid
    if cid is not None:
        # kinga: rekodi ya kampuni nyingine haiwezi kubadilishwa kutoka hapa
        for obj in session.dirty:
            if isinstance(obj, EntityBase) and obj.company_id not in (None, cid):
                from .core.exceptions import PermissionDenied

                raise PermissionDenied("Data ya kampuni nyingine")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_database_if_not_exists(database: str | None = None) -> None:
    """Inaunda database kwenye PostgreSQL kama bado haipo."""
    name = database or config.DATABASE_NAME
    admin_engine = create_engine(database_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
                logger.info("Database '%s' imeundwa.", name)
    finally:
        admin_engine.dispose()


def init_db() -> None:
    """Inaunda database na tables zote ambazo bado hazipo (haigusi data iliyopo)."""
    create_database_if_not_exists()
    from . import models  # noqa: F401  (inasajili models zote kwenye Base.metadata)

    register_tenant_events()
    Base.metadata.create_all(bind=engine)
    sync_schema()


def sync_schema() -> None:
    """
    Inaongeza columns na indexes mpya kwenye tables zilizopo (create_all haiongezi columns).
    Column mpya inayohitajika (NOT NULL) lazima iwe na `server_default`, vinginevyo inaongezwa kama NULL.
    """
    from . import models  # noqa: F401

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{column.name}" ' \
                      f'{column.type.compile(dialect=engine.dialect)}'
                if column.server_default is not None:
                    arg = column.server_default.arg
                    value = "'" + arg.replace("'", "''") + "'" if isinstance(arg, str) else str(arg)
                    ddl += f" DEFAULT {value}"
                    if not column.nullable:
                        ddl += " NOT NULL"
                conn.execute(text(ddl))
                logger.info("Column mpya: %s.%s", table.name, column.name)
    with engine.begin() as conn:
        for sql in _MIGRATIONS:
            conn.execute(text(sql))
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(bind=engine, checkfirst=True)


# Mabadiliko ya muundo ambayo create_all/sync haiwezi kufanya (lazima yawe salama kurudiwa).
_MIGRATIONS = [
    # v2.7: makabidhiano kadhaa kwa ankara moja (kukabidhi kwa awamu)
    'ALTER TABLE IF EXISTS handovers DROP CONSTRAINT IF EXISTS handovers_invoice_id_key',
    # v2.10: namba ya simu si lazima (muundo +255XXXXXXXXX)
    'ALTER TABLE IF EXISTS customers ALTER COLUMN "phoneNumber" DROP NOT NULL',
    'ALTER TABLE IF EXISTS users ALTER COLUMN "phoneNumber" DROP NOT NULL',
    'ALTER TABLE IF EXISTS receivers ALTER COLUMN "phoneNumber" DROP NOT NULL',
    'ALTER TABLE IF EXISTS handovers ALTER COLUMN "collectorPhone" DROP NOT NULL',
    # v2.12: code ya ofisi ni ya kila mzigo (products.officeCode), si ya ankara
    'DROP INDEX IF EXISTS ux_invoices_office_code',
    'ALTER TABLE IF EXISTS invoices DROP COLUMN IF EXISTS "officeCode"',
    # SaaS v1: vitu vya kipekee sasa ni vya kipekee ndani ya kampuni moja tu (indexes ux_* zenye company_id)
    'ALTER TABLE IF EXISTS users DROP CONSTRAINT IF EXISTS users_username_key',
    'ALTER TABLE IF EXISTS users DROP CONSTRAINT IF EXISTS "users_phoneNumber_key"',
    'ALTER TABLE IF EXISTS customers DROP CONSTRAINT IF EXISTS "customers_phoneNumber_key"',
    'ALTER TABLE IF EXISTS invoices DROP CONSTRAINT IF EXISTS "invoices_invoiceNumber_key"',
    'ALTER TABLE IF EXISTS quotations DROP CONSTRAINT IF EXISTS quotations_number_key',
    'ALTER TABLE IF EXISTS institutes DROP CONSTRAINT IF EXISTS "institutes_accountNo_key"',
    'ALTER TABLE IF EXISTS "smsSet" DROP CONSTRAINT IF EXISTS "smsSet_name_key"',
    'ALTER TABLE IF EXISTS packages DROP CONSTRAINT IF EXISTS "packages_boxId_key"',
    'ALTER TABLE IF EXISTS receivers DROP CONSTRAINT IF EXISTS "receivers_trackNumber_key"',
    'ALTER TABLE IF EXISTS roles DROP CONSTRAINT IF EXISTS roles_name_key',
    'ALTER TABLE IF EXISTS cashups DROP CONSTRAINT IF EXISTS uq_cashup_day_office',
    'DROP INDEX IF EXISTS ux_products_office_code',
]
