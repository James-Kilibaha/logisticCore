from sqlalchemy.orm import Session

from ..core.enums import Module
from ..core.exceptions import Conflict, NotFound
from . import schema
from .dao import PermissionDao
from .model import Permission

FLAGS = ("data_insert", "data_update", "data_select", "data_delete", "data_block")


# Moduli mpya zilizogawanywa kutoka za zamani. Mtumiaji (au role) aliyekuwepo kabla moduli mpya haijaongezwa
# anarithi ruhusa kutoka moduli ya zamani iliyokuwa ikifanya kazi hiyo - ili kazi isisimame siku ya kusasisha.
# {moduli_mpya: {kitendo_kipya: [(moduli_ya_zamani, kitendo), ...]}}  (yoyote ikiwa kweli -> kweli)
S, I, U, D, B = "select", "insert", "update", "delete", "block"
INHERIT: dict[str, dict[str, list[tuple[str, str]]]] = {
    "DASHBOARD": {S: [("PAYMENT", S), ("REPORT", S)]},
    "HANDOVER": {S: [("PAYMENT", S)], I: [("PAYMENT", I)], U: [("PAYMENT", U)]},
    "DISCOUNT": {S: [("PAYMENT", U)], I: [("PAYMENT", U)]},
    "REFUND": {S: [("PAYMENT", U)], I: [("PAYMENT", U)]},
    "CREDIT": {S: [("PAYMENT", S)], U: [("PAYMENT", U)]},
    "CLAIM": {S: [("STORE", S)], I: [("STORE", I)], U: [("PAYMENT", U)]},
    "CASHUP": {S: [("PAYMENT", S)], I: [("PAYMENT", U)], D: [("PAYMENT", D)]},
    "BROADCAST": {S: [("SMS", I)], I: [("SMS", I)]},
    "WHATSAPP": {S: [("SMS", S)], I: [("SMS", I)]},
    "PROFIT": {S: [("REPORT", S)], U: [("PACKAGE", U)], D: [("PACKAGE", D)]},
    "FINANCE": {S: [("PAYMENT", S), ("REPORT", S)]},
    "AUDIT": {S: [("PERMISSION", S)]},
    "BACKUP": {S: [("SETTING", S)], I: [("SETTING", I)], D: [("SETTING", D)]},
    "IMPORT": {S: [("SETTING", I)], I: [("SETTING", I)]},
    "PRICE": {S: [("SETTING", S), ("INVOICE", I)], I: [("SETTING", I)], U: [("SETTING", U)], D: [("SETTING", D)]},
    "QUOTE": {S: [("INVOICE", S)], I: [("INVOICE", I)], U: [("INVOICE", I)], D: [("INVOICE", D)]},
    # mwenye uwezo wa kufuta matumizi (msimamizi / mhasibu) anapata uhasibu kamili
    "ACCOUNTING": {S: [("FINANCE", S)], I: [("EXPENSES", D)], U: [("EXPENSES", D)], D: [("EXPENSES", D)]},
    "PAYROLL": {S: [("ACCOUNTING", U)], I: [("ACCOUNTING", U)], U: [("ACCOUNTING", U)], D: [("ACCOUNTING", D)]},
}


def inherited_flags(module: str, old: dict[str, dict[str, bool]]) -> dict[str, bool]:
    """Ruhusa za moduli mpya kutoka ruhusa za zamani: old = {moduli: {"select": bool, ...}}."""
    rules = INHERIT.get(module, {})
    return {f"data_{action}": any(old.get(m, {}).get(a, False) for m, a in sources)
            for action, sources in ((x, rules.get(x, [])) for x in (S, I, U, D, B))}


def _role_flags(db: Session, user_id) -> dict[str, dict[str, bool]]:
    from ..role.model import RolePermission
    from ..user.model import User

    user = db.get(User, user_id)
    if user is None or getattr(user, "role_id", None) is None:
        return {}
    rows = db.query(RolePermission).filter(RolePermission.role_id == user.role_id).all()
    return {r.module: {flag: bool(getattr(r, flag)) for flag in FLAGS} for r in rows}


def ensure_defaults(db: Session, user_id, grant_all: bool = False) -> None:
    """Inahakikisha mtumiaji ana mstari wa ruhusa kwa kila moduli (bila kubadilisha zilizopo)."""
    dao = PermissionDao(db)
    rows = dao.for_user(user_id)
    existing = {p.name for p in rows}
    old = {p.name: {f[5:]: bool(getattr(p, f)) for f in FLAGS} for p in rows}
    missing = [m.value for m in Module if m.value not in existing]
    role_flags = _role_flags(db, user_id) if missing and not grant_all else {}
    for name in missing:
        if grant_all:
            flags = {flag: True for flag in FLAGS}
        elif name in role_flags:  # mtumiaji mwenye role: moduli mpya inafuata role yake
            flags = role_flags[name]
        elif existing:  # mtumiaji wa zamani: rithi kutoka moduli za zamani
            flags = inherited_flags(name, old)
        else:
            flags = {flag: False for flag in FLAGS}
        dao.create(commit=False, name=name, logsId=user_id, user_id=user_id, **flags)
    if missing:
        db.commit()


def ensure_defaults_for_all_users(db: Session) -> None:
    from ..user.dao import UserDao

    for user in UserDao(db).all():
        ensure_defaults(db, user.id)


def create(db: Session, data: schema.PermissionCreate, current_user_id) -> Permission:
    dao = PermissionDao(db)
    if dao.by_name(data.user_id, data.name):
        raise Conflict("This permission already exists")
    return dao.create(name=data.name, user_id=data.user_id, logsId=current_user_id,
                      **data.model_dump(include=set(FLAGS)))


def update(db: Session, data: schema.PermissionUpdate) -> Permission:
    dao = PermissionDao(db)
    permission = dao.by_id(data.user_id, data.id)
    if permission is None:
        raise NotFound("This permission does not exist...")
    return dao.update(permission, **data.model_dump(include=set(FLAGS)))


def list_for_user(db: Session, user_id):
    permissions = PermissionDao(db).for_user(user_id)
    if not permissions:
        raise NotFound("The user does not have any permission")
    return permissions
