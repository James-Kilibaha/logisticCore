from sqlalchemy.orm import Session

from ..core.exceptions import BadRequest, Conflict, NotFound
from ..core.audit import note
from ..core.security import hash_password, password_problem
from ..core import phone as phones
from ..core.utils import title
from ..permission import service as permission_service
from . import schema
from .dao import UserDao
from .model import User


def _get_or_404(dao: UserDao, user_id) -> User:
    user = dao.get(user_id)
    if user is None:
        raise NotFound("The user does not exist")
    return user


def create(db: Session, data: schema.UserCreate, grant_all: bool = False) -> User:
    dao = UserDao(db)
    phone = phones.normalize(data.phoneNumber)
    if phone and dao.by_phone(phone):
        raise Conflict("The phone number is Exited")
    if dao.by_username(data.username.strip()):
        raise Conflict("The username is Exited")
    if not grant_all:  # (msimamizi wa kwanza wa kampuni mpya haguswi na mipaka)
        from ..saas.subscription.service import check_limit

        check_limit(db, "users")
    problem = password_problem(data.password)
    if problem:
        raise BadRequest(problem)

    user = dao.create(
        firstName=title(data.firstName),
        lastName=title(data.lastName),
        phoneNumber=phone,
        username=data.username.strip(),
        password=hash_password(data.password),
        active=1,
        office_id=data.office_id,
        allOffices=data.allOffices,
        # Aliyeundwa na msimamizi anaweka nywila yake mwenyewe akiingia mara ya kwanza.
        mustChangePassword=not grant_all,
    )
    permission_service.ensure_defaults(db, user.id, grant_all=grant_all)
    if data.role_id is not None:
        from ..role import service as role_service
        from ..role.schema import Assign

        role_service.assign(db, Assign(user_id=user.id, role_id=data.role_id))
        db.refresh(user)
    return user


def update(db: Session, data: schema.UserUpdate) -> User:
    dao = UserDao(db)
    user = _get_or_404(dao, data.id)
    phone = phones.normalize(data.phoneNumber)
    other = dao.by_phone(phone) if phone else None
    if other and other.id != user.id:
        raise Conflict("The phone number is Exited")

    # Ofisi isipotumwa, ofisi ya sasa inabaki (app haitumi ofisi kama haikubadilishwa).
    user = dao.update(user, firstName=title(data.firstName), lastName=title(data.lastName),
                      phoneNumber=phone, office_id=data.office_id or user.office_id,
                      allOffices=user.allOffices if data.allOffices is None else data.allOffices)
    permission_service.ensure_defaults(db, user.id)
    return user


def change_password(db: Session, data: schema.UserChangePass) -> User:
    dao = UserDao(db)
    user = _get_or_404(dao, data.id)
    problem = password_problem(data.password)
    if problem:
        raise BadRequest(problem)
    note(f"{user.username}: nywila imewekwa upya na msimamizi")
    # Nywila ya muda: mtumiaji ataibadilisha akiingia; vifaa vyake vyote vinatolewa.
    return dao.update(user, password=hash_password(data.password), mustChangePassword=True,
                      tokenVersion=int(user.tokenVersion or 0) + 1)


def toggle_block(db: Session, user_id) -> User:
    dao = UserDao(db)
    user = _get_or_404(dao, user_id)
    return dao.update(user, active=0 if user.active == 1 else 1, tokenVersion=int(user.tokenVersion or 0) + 1)


def logout_everywhere(db: Session, user_id) -> User:
    dao = UserDao(db)
    user = _get_or_404(dao, user_id)
    note(f"{user.username}: ametolewa kwenye vifaa vyote na msimamizi")
    return dao.update(user, tokenVersion=int(user.tokenVersion or 0) + 1)


def list_all(db: Session):
    return UserDao(db).all_with_office()


def get(db: Session, user_id) -> User:
    return _get_or_404(UserDao(db), user_id)


def delete(db: Session, user_id) -> bool:
    dao = UserDao(db)
    return dao.delete(_get_or_404(dao, user_id))


def set_two_factor(db: Session, data: schema.TwoFactor) -> User:
    from ..core.audit import note

    dao = UserDao(db)
    user = _get_or_404(dao, data.id)
    if data.enabled and not phones.try_normalize(user.phoneNumber):
        raise BadRequest("Weka namba sahihi ya simu ya mtumiaji kwanza (mf. +255712345678) - code inatumwa kwa SMS")
    user = dao.update(user, twoFactor=data.enabled, otpHash=None, otpExpires=None, otpAttempts=0)
    note(f"2FA ya {user.username}: {'imewashwa' if data.enabled else 'imezimwa'}")
    return user
