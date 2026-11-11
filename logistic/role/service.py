from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from ..core.audit import note
from ..core.enums import Module
from ..core.exceptions import BadRequest, Conflict, NotFound
from ..permission.dao import PermissionDao
from ..permission.service import FLAGS, ensure_defaults
from ..user.model import User
from . import schema
from .model import Role, RolePermission

S, I, U, D, B = "select", "insert", "update", "delete", "block"

# Role za kuanzia. Msimamizi anaweza kuzibadilisha (isipokuwa kufuta).
DEFAULT_ROLES: dict[str, tuple[str, dict[str, set[str]]]] = {
    "Msimamizi": ("Ruhusa zote", {m.value: {S, I, U, D, B} for m in Module}),
    "Mpokeaji China": ("Kupokea mizigo, kusajili wateja na ankara, kupakia mabox", {
        "CUSTOMER": {S, I, U}, "INVOICE": {S, I, U}, "PRODUCT": {S, I, U, D}, "RECEIVE": {S, I, U},
        "PACKAGE": {S, I, U}, "SETTING": {S}, "PRICE": {S}, "QUOTE": {S, I, U}, "SMS": {S, I}, "WHATSAPP": {S, I},
        "EXPENSES": {S, I, U}}),
    "Stoo Tanzania": ("Kupokea mabox, ankara za stoo na kukabidhi mizigo", {
        "CUSTOMER": {S}, "INVOICE": {S}, "PRODUCT": {S}, "RECEIVE": {S}, "PACKAGE": {S, U},
        "STORE": {S, I, U}, "PAYMENT": {S, I}, "HANDOVER": {S, I}, "CLAIM": {S, I}, "SETTING": {S}, "PRICE": {S},
        "SMS": {S, I}, "WHATSAPP": {S, I}, "EXPENSES": {S, I, U}}),
    "Mhasibu": ("Mhasibu (Accountant): uhasibu kamili - akaunti, mapato, matumizi na kuyaidhinisha, faida/hasara", {
        "CUSTOMER": {S}, "INVOICE": {S}, "PRODUCT": {S}, "STORE": {S, I}, "PAYMENT": {S, I, U},
        "HANDOVER": {S}, "DISCOUNT": {S, I}, "REFUND": {S, I}, "CREDIT": {S}, "CLAIM": {S, U},
        "CASHUP": {S, I}, "FINANCE": {S}, "DASHBOARD": {S}, "PROFIT": {S, I, U},
        "EXPENSES": {S, I, U, D}, "REPORT": {S, I}, "SETTING": {S}, "PRICE": {S}, "QUOTE": {S},
        "ACCOUNTING": {S, I, U, D}, "PAYROLL": {S, I, U, D}}),
    "Mtazamaji": ("Kuona tu - hawezi kubadilisha chochote", {
        m.value: {S} for m in Module if m.value not in ("FINANCE", "DASHBOARD", "PROFIT", "AUDIT", "BACKUP",
                                                          "CASHUP", "IMPORT", "BROADCAST", "PERMISSION",
                                                          "ACCOUNTING", "PAYROLL")}),
}


# Kila vipengele vipya vikiongezwa: moduli hizi zinapewa ruhusa za kuanzia kwenye role za MFUMO zilizopo (mara moja).
# Ruhusa zinaongezwa tu (hazipunguzwi), na watumiaji wa role hizo wanazipata pia.
DEFAULTS_VERSION = 3
UPGRADES: dict[int, tuple[str, ...]] = {
    2: ("EXPENSES", "ACCOUNTING", "PROFIT"),   # v2.15-2.17: uhasibu, matumizi yenye idhini, gharama/madeni ya mabox
    3: ("PAYROLL",),                           # v2.18: mishahara
}


def _flags(actions: set[str]) -> dict:
    return {f"data_{a}": a in actions for a in (S, I, U, D, B)}


def ensure_defaults_roles(db: Session) -> None:
    """
    Inaunda role za kuanzia ambazo bado hazipo, na kuongeza moduli mpya kwenye role zilizopo:
    role za mfumo zinapata ruhusa zilizopendekezwa (DEFAULT_ROLES); role zako zinarithi kutoka moduli za zamani.
    """
    from ..permission.service import inherited_flags

    roles = {r.name: r for r in db.query(Role).options(selectinload(Role.permissions)).all()}
    for name, (description, perms) in DEFAULT_ROLES.items():
        if name in roles:
            continue
        role = Role(name=name, description=description, isSystem=True, defaultsVersion=DEFAULTS_VERSION)
        role.permissions = [RolePermission(module=m.value, **_flags(perms.get(m.value, set()))) for m in Module]
        db.add(role)
    for name, role in roles.items():
        have = {p.module for p in role.permissions}
        missing = [m.value for m in Module if m.value not in have]
        if not missing:
            continue
        old = {p.module: {f[5:]: bool(getattr(p, f)) for f in FLAGS} for p in role.permissions}
        for module in missing:
            if role.isSystem and name in DEFAULT_ROLES:
                flags = _flags(DEFAULT_ROLES[name][1].get(module, set()))
            else:
                flags = inherited_flags(module, old)
            role.permissions.append(RolePermission(module=module, **flags))
    db.commit()
    _upgrade_system_roles(db)


def _upgrade_system_roles(db: Session) -> None:
    from ..permission.model import Permission

    for role in db.query(Role).options(selectinload(Role.permissions)).filter(Role.isSystem.is_(True)).all():
        version = role.defaultsVersion or 0
        if version >= DEFAULTS_VERSION:
            continue
        defaults = DEFAULT_ROLES.get(role.name, (None, {}))[1]
        modules = {m for v, mods in UPGRADES.items() if v > version for m in mods}
        rows = {p.module: p for p in role.permissions}
        changed = []
        for module in modules:
            wanted = defaults.get(module, set())
            row = rows.get(module)
            if not wanted or row is None:
                continue
            added = [a for a in wanted if not getattr(row, f"data_{a}")]
            for a in added:
                setattr(row, f"data_{a}", True)
            if added:
                changed.append((module, added))
        user_ids = [u for (u,) in db.query(User.id).filter(User.role_id == role.id).all()]
        for module, added in changed:
            for perm in db.query(Permission).filter(Permission.user_id.in_(user_ids), Permission.name == module).all():
                for a in added:
                    setattr(perm, f"data_{a}", True)
        role.defaultsVersion = DEFAULTS_VERSION
        if changed:
            note(f"Role '{role.name}': ruhusa mpya za kuanzia - " + ", ".join(f"{m} ({'/'.join(a)})" for m, a in changed))
    db.commit()


def _users_count(db: Session) -> dict:
    return dict(db.query(User.role_id, func.count(User.id)).filter(User.role_id.isnot(None))
                .group_by(User.role_id).all())


def _display(role: Role, counts: dict) -> schema.Display:
    out = schema.Display.model_validate(role)
    out.users = counts.get(role.id, 0)
    # moduli zote zionekane hata kama role ilikosa mstari
    have = {p.module for p in out.permissions}
    out.permissions += [schema.ModuleFlags(module=m.value) for m in Module if m.value not in have]
    out.permissions.sort(key=lambda p: p.module)
    return out


def _get(db: Session, role_id) -> Role:
    from ..core.dao import to_uuid

    role = db.query(Role).options(selectinload(Role.permissions)).filter(Role.id == to_uuid(role_id)).one_or_none()
    if role is None:
        raise NotFound("Role not found")
    return role


def list_all(db: Session) -> list[schema.Display]:
    counts = _users_count(db)
    roles = db.query(Role).options(selectinload(Role.permissions)).order_by(Role.name).all()
    return [_display(r, counts) for r in roles]


def _set_permissions(role: Role, items: list[schema.ModuleFlags]) -> None:
    valid = {m.value for m in Module}
    by_module = {p.module: p for p in role.permissions}
    for item in items:
        module = item.module.upper()
        if module not in valid:
            raise BadRequest(f"Unknown module {item.module}")
        row = by_module.get(module)
        if row is None:
            row = RolePermission(module=module)
            role.permissions.append(row)
            by_module[module] = row
        for flag in FLAGS:
            setattr(row, flag, getattr(item, flag))


def apply_to_user(db: Session, role: Role, user_id) -> None:
    """Ruhusa za mtumiaji = ruhusa za role."""
    ensure_defaults(db, user_id)
    dao = PermissionDao(db)
    by_module = {p.module: p for p in role.permissions}
    for perm in dao.for_user(user_id):
        source = by_module.get(perm.name)
        for flag in FLAGS:
            setattr(perm, flag, bool(getattr(source, flag)) if source is not None else False)
        db.add(perm)


def create(db: Session, data: schema.Save) -> schema.Display:
    name = data.name.strip()
    if db.query(Role).filter(func.lower(Role.name) == name.lower()).first():
        raise Conflict("A role with this name already exists")
    role = Role(name=name, description=(data.description or "").strip() or None, isSystem=False)
    role.permissions = []
    _set_permissions(role, data.permissions)
    db.add(role)
    db.commit()
    note(f"Role mpya: {name}")
    return _display(_get(db, role.id), _users_count(db))


def update(db: Session, role_id, data: schema.Save) -> schema.Display:
    role = _get(db, role_id)
    name = data.name.strip()
    other = db.query(Role).filter(func.lower(Role.name) == name.lower(), Role.id != role.id).first()
    if other:
        raise Conflict("A role with this name already exists")
    role.name = name
    role.description = (data.description or "").strip() or None
    _set_permissions(role, data.permissions)
    db.flush()
    users = db.query(User.id).filter(User.role_id == role.id).all() if data.applyToUsers else []
    for (user_id,) in users:
        apply_to_user(db, role, user_id)
    db.commit()
    note(f"Role '{name}' imebadilishwa" + (f"; watumiaji {len(users)} wamesasishwa" if users else ""))
    return _display(_get(db, role.id), _users_count(db))


def delete(db: Session, role_id) -> bool:
    role = _get(db, role_id)
    if role.isSystem:
        raise BadRequest("System roles cannot be deleted (you can edit them)")
    if db.query(User.id).filter(User.role_id == role.id).first():
        raise BadRequest("This role still has users. Move them to another role first")
    db.delete(role)
    db.commit()
    note(f"Role '{role.name}' imefutwa")
    return True


def assign(db: Session, data: schema.Assign) -> dict:
    from ..user.dao import UserDao

    user = UserDao(db).get(data.user_id)
    if user is None:
        raise NotFound("The user does not exist")
    if data.role_id is None:
        user.role_id = None
        db.commit()
        return {"user_id": str(user.id), "role_id": None}
    role = _get(db, data.role_id)
    user.role_id = role.id
    apply_to_user(db, role, user.id)
    db.commit()
    note(f"{user.username} amepewa role '{role.name}'")
    return {"user_id": str(user.id), "role_id": str(role.id), "role": role.name}
