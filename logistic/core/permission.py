"""
Ukaguzi wa ruhusa (permission) kama dependency moja ya FastAPI.

Badala ya kurudia `if await monitor.PERMISSION(...) is None: raise ...` kila endpoint,
router inaandika tu:

    current_user = Depends(require(Module.CUSTOMER, Action.INSERT))
"""
from fastapi import Depends
from sqlalchemy.orm import Session

from ..db import get_db
from .enums import Action, Module
from .exceptions import AppError, PermissionDenied
from .security import TokenData, get_current_user

_VERB = {
    Action.INSERT: "register",
    Action.UPDATE: "update",
    Action.SELECT: "view",
    Action.DELETE: "delete",
    Action.BLOCK: "block",
}


# Madai ya gharama yaliyopitwa na muda yanazuia kuandika/kubadilisha - isipokuwa sehemu za kujaza gharama zenyewe.
_GUARD_EXEMPT = {Module.EXPENSES, Module.ACCOUNTING, Module.PROFIT}


def _guard(db: Session, user_id, pairs) -> None:
    if any(a == Action.SELECT or m in _GUARD_EXEMPT for m, a in pairs):
        return
    from ..demand.service import guard

    guard(db, user_id)


def require(module: Module, action: Action):
    def dependency(current_user: TokenData = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> TokenData:
        from ..permission.dao import PermissionDao  # import ya ndani kuepuka mzunguko

        if current_user.mustChangePassword:
            # 428: app inaonyesha skrini ya kubadilisha nywila
            raise AppError("Password change required", status_code=428)
        if _viewer_reads(current_user, action):
            return current_user
        if not PermissionDao(db).has(current_user.id, module.value, action.value):
            raise PermissionDenied(f"You do not have permission to {_VERB[action]} {module.value.title()}")
        _in_plan(module)
        _guard(db, current_user.id, [(module, action)])
        return current_user

    return dependency


def _viewer_reads(current_user: TokenData, *actions: Action) -> bool:
    """Super admin anaangalia kampuni (token ya kusoma tu): anaona kila ukurasa. Kubadilisha kunazuiwa na middleware."""
    return bool(getattr(current_user, "imp", None)) and all(a == Action.SELECT for a in actions)


def _in_plan(module: Module) -> None:
    """Moduli za ziada (WhatsApp, makadirio, faida ...) zinategemea mpango wa subscription wa kampuni."""
    from ..saas.subscription.service import ensure_module

    ensure_module(module.value)


def allowed(db: Session, user_id, module: Module, action: Action = Action.SELECT) -> bool:
    from ..permission.dao import PermissionDao

    return PermissionDao(db).has(user_id, module.value, action.value)


def need(db: Session, user_id, module: Module, action: Action = Action.SELECT) -> None:
    """Ukaguzi wa ziada ndani ya endpoint (kwa mfano kulingana na data iliyotumwa)."""
    if not allowed(db, user_id, module, action):
        raise PermissionDenied(f"You do not have permission to {_VERB[action]} {module.value.title()}")
    _in_plan(module)


def require_all(*pairs: tuple[Module, Action]):
    """Kama require(), lakini ruhusa zote zilizotajwa zinahitajika."""
    def dependency(current_user: TokenData = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> TokenData:
        if current_user.mustChangePassword:
            raise AppError("Password change required", status_code=428)
        if _viewer_reads(current_user, *[a for _, a in pairs]):
            return current_user
        for module, action in pairs:
            need(db, current_user.id, module, action)
            _in_plan(module)
        _guard(db, current_user.id, pairs)
        return current_user

    return dependency


def require_any(*pairs: tuple[Module, Action]):
    """Kama require(), lakini ruhusa moja kati ya zilizotajwa inatosha."""
    def dependency(current_user: TokenData = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> TokenData:
        if current_user.mustChangePassword:
            raise AppError("Password change required", status_code=428)
        if _viewer_reads(current_user, *[a for _, a in pairs]):
            return current_user
        from ..saas.subscription.service import module_allowed

        in_plan = [(m, a) for m, a in pairs if module_allowed(m.value)]
        if not in_plan:
            _in_plan(pairs[0][0])
        if not any(allowed(db, current_user.id, m, a) for m, a in in_plan):
            module, action = pairs[0]
            raise PermissionDenied(f"You do not have permission to {_VERB[action]} {module.value.title()}")
        _guard(db, current_user.id, pairs)
        return current_user

    return dependency
