from sqlalchemy.orm import Session

from .. import config
from ..core import audit, ratelimit
from ..core.exceptions import AppError, NotFound
from ..core.security import create_access_token, create_refresh_token, decode_refresh_token, verify_password
from ..user.dao import UserDao
from ..user.model import User
from ..user.schema import AuthUser
from . import schema


def _tokens(user: User) -> schema.LoginResponse:
    claims = {"id": str(user.id), "sub": user.username, "ver": int(user.tokenVersion or 0),
              "cid": str(user.company_id)}
    return schema.LoginResponse(access_token=create_access_token(claims), refresh_token=create_refresh_token(claims),
                                expires_in=config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                                user=AuthUser.model_validate(user))


def _log(user_id, username: str, ok: bool, ip: str | None, summary: str, action: str = "LOGIN") -> None:
    audit.write(user_id=user_id, username=username[:100], module="auth", action=action, method="POST",
                path="/api/login", entity_id=str(user_id) if user_id else None, status_code=200 if ok else 401,
                ip=ip, summary=summary, detail=None)


def _otp_login_enabled(db: Session) -> bool:
    """Swichi "Code ya kuingia (2FA)" ikizimwa (Mipangilio → Aina za SMS), 2FA inasimamishwa kwa wote."""
    from ..core.enums import ESmsStatus
    from ..sms.service import kind_enabled

    return kind_enabled(db, ESmsStatus.OTP_LOGIN)


def login(db: Session, data: schema.Login, ip: str | None = None) -> schema.LoginResponse:
    from ..core import tenant

    tenant.require_company_id()  # kampuni lazima ijulikane (domain au code ya kampuni)
    username = data.username.strip()
    ratelimit.check(username, ip)
    user = UserDao(db).by_username(username)
    if user is None or not verify_password(data.password, user.password):
        ratelimit.failed(username, ip)
        _log(user.id if user else None, username, False, ip, "Nywila au jina si sahihi")
        raise NotFound("Incorrect username or password")
    if user.active == 0:
        _log(user.id, username, False, ip, "Mtumiaji amezuiwa")
        raise NotFound("User is not active")

    if config.TWO_FACTOR_ENABLED and user.twoFactor and _otp_login_enabled(db):
        from . import otp

        otp.send(db, user, force=True)
        _log(user.id, username, True, ip, "Nywila sahihi - code ya SMS imetumwa (2FA)", action="LOGIN_OTP_SENT")
        return schema.LoginResponse(otpRequired=True, otpToken=otp.challenge_token(user),
                                    phoneHint=otp.phone_hint(user.phoneNumber), otpTtlMinutes=config.OTP_TTL_MINUTES)
    ratelimit.succeeded(username)
    _log(user.id, username, True, ip, "Ameingia")
    return _tokens(user)


def verify_otp(db: Session, data: schema.OtpVerify, ip: str | None = None) -> schema.LoginResponse:
    from . import otp

    user = otp.user_from_token(db, data.otpToken)
    try:
        otp.verify(db, user, data.code)
    except AppError:
        _log(user.id, user.username, False, ip, "Code ya SMS (2FA) si sahihi", action="LOGIN_OTP")
        raise
    ratelimit.succeeded(user.username)
    _log(user.id, user.username, True, ip, "Ameingia (code ya SMS)")
    return _tokens(user)


def resend_otp(db: Session, data: schema.OtpResend) -> schema.LoginResponse:
    from . import otp

    user = otp.user_from_token(db, data.otpToken)
    otp.send(db, user)
    return schema.LoginResponse(otpRequired=True, otpToken=otp.challenge_token(user),
                                phoneHint=otp.phone_hint(user.phoneNumber), otpTtlMinutes=config.OTP_TTL_MINUTES)


def refresh(db: Session, data: schema.Refresh) -> schema.LoginResponse:
    from ..core import tenant

    token = decode_refresh_token(data.refresh_token)
    if token is not None and token.cid != tenant.company_id():
        token = None  # refresh token ya kampuni nyingine
    user = UserDao(db).get(token.id) if token else None
    if user is None or user.active == 0 or int(user.tokenVersion or 0) != token.ver:
        raise AppError("Session expired, please log in again", status_code=401)
    return _tokens(user)


def change_own_password(db: Session, user_id, data) -> schema.LoginResponse:
    """Mtumiaji anabadilisha nywila yake; vifaa vingine vinatolewa, kifaa hiki kinapata token mpya."""
    from ..core.exceptions import BadRequest
    from ..core.security import hash_password, password_problem

    user = UserDao(db).get(user_id)
    if user is None:
        raise NotFound("The user does not exist")
    if not verify_password(data.oldPassword, user.password):
        raise BadRequest("Current password is not correct")
    if data.oldPassword == data.newPassword:
        raise BadRequest("New password must be different from the current one")
    problem = password_problem(data.newPassword)
    if problem:
        raise BadRequest(problem)
    user.password = hash_password(data.newPassword)
    user.mustChangePassword = False
    user.tokenVersion = int(user.tokenVersion or 0) + 1
    db.commit()
    db.refresh(user)
    audit.note("Amebadilisha nywila yake")
    return _tokens(user)


def logout_everywhere(db: Session, user_id) -> bool:
    user = UserDao(db).get(user_id)
    if user is None:
        raise NotFound("The user does not exist")
    user.tokenVersion = int(user.tokenVersion or 0) + 1
    db.commit()
    audit.note(f"{user.username}: ametolewa kwenye vifaa vyote")
    return True


# ------------------------------------------------------------- kusahau nywila (code ya SMS)
def forgot(db: Session, data: schema.Forgot, ip: str | None = None) -> dict:
    """
    Kusahau nywila, hatua ya 1: code ya SMS inatumwa kwenye namba ya mtumiaji.
    Mtumiaji anaweza kuandika jina lake la mtumiaji (herufi kubwa/ndogo hazijalishi) au namba yake ya simu.
    Kama code haiwezi kutumwa, sababu halisi inarudishwa (hakuna mtumiaji, hana namba, gateway imekataa...).
    """
    from sqlalchemy import func

    from ..core.exceptions import BadRequest
    from ..core.phone import try_normalize
    from ..core import tenant
    from . import otp

    tenant.require_company_id()
    value = (data.username or "").strip()
    if not value:
        raise BadRequest("Andika jina la mtumiaji au namba ya simu / enter your username or phone number")
    ratelimit.hit(f"forgot:{ip or '-'}", limit=10, window_seconds=900)
    ratelimit.hit(f"forgot-user:{value.lower()}", limit=5, window_seconds=900)

    user = db.query(User).filter(func.lower(User.username) == value.lower()).first()
    phone = try_normalize(value) if user is None else None
    if user is None and phone:
        user = UserDao(db).by_phone(phone)
    if user is None:
        _log(None, value, False, ip, "Kusahau nywila: mtumiaji hakupatikana", action="PASSWORD_FORGOT")
        raise BadRequest("Hakuna mtumiaji mwenye jina au namba hii / no user with this username or phone")
    if user.active == 0:
        _log(user.id, user.username, False, ip, "Kusahau nywila: akaunti imezuiwa", action="PASSWORD_FORGOT")
        raise BadRequest("Akaunti hii imezuiwa - wasiliana na msimamizi / this account is blocked")
    from ..core.enums import ESmsStatus
    from ..sms.service import ensure_enabled

    try:
        ensure_enabled(db, ESmsStatus.OTP_RESET)
    except BadRequest:
        _log(user.id, user.username, False, ip, "Kusahau nywila: SMS za code zimezimwa", action="PASSWORD_FORGOT")
        raise
    if not try_normalize(user.phoneNumber):
        _log(user.id, user.username, False, ip, "Kusahau nywila: hana namba ya simu", action="PASSWORD_FORGOT")
        raise BadRequest("Akaunti hii haina namba sahihi ya simu, kwa hiyo code haiwezi kutumwa. Muombe msimamizi "
                         "akuwekee nywila mpya / this account has no valid phone number - ask an administrator")
    try:
        otp.send(db, user, purpose="reset")
    except AppError as error:
        _log(user.id, user.username, False, ip, f"Kusahau nywila: code haikutumwa ({error.detail})"[:300],
             action="PASSWORD_FORGOT")
        raise
    _log(user.id, user.username, True, ip, "Kusahau nywila: code ya SMS imetumwa", action="PASSWORD_FORGOT")
    return {"resetToken": otp.challenge_token(user, kind="reset"), "ttlMinutes": config.OTP_TTL_MINUTES,
            "phoneHint": otp.phone_hint(user.phoneNumber), "username": user.username,
            "message": f"Code imetumwa kwa SMS kwenda {otp.phone_hint(user.phoneNumber)}"}


def forgot_reset(db: Session, data: schema.ForgotReset, ip: str | None = None) -> dict:
    from ..core.exceptions import BadRequest
    from ..core.security import hash_password, password_problem
    from . import otp

    ratelimit.hit(f"forgot-reset:{ip or '-'}", limit=20, window_seconds=900)
    try:
        user = otp.user_from_token(db, data.resetToken, kind="reset")
    except NotFound:
        raise BadRequest("Code si sahihi au imeisha muda / wrong or expired code")
    problem = password_problem(data.newPassword)
    if problem:
        raise BadRequest(problem)
    try:
        otp.verify(db, user, data.code)
    except AppError:
        _log(user.id, user.username, False, ip, "Kusahau nywila: code si sahihi", action="PASSWORD_RESET")
        raise
    user.password = hash_password(data.newPassword)
    user.mustChangePassword = False
    user.tokenVersion = int(user.tokenVersion or 0) + 1  # vifaa vyote vinatolewa
    db.commit()
    ratelimit.succeeded(user.username)
    _log(user.id, user.username, True, ip, "Amebadilisha nywila kwa code ya SMS", action="PASSWORD_RESET")
    return {"ok": True, "username": user.username}
