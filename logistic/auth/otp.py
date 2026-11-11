"""
Uthibitisho wa hatua mbili (2FA): baada ya nywila sahihi, code ya tarakimu 6 inatumwa kwa SMS kwenye simu ya
mtumiaji. Code inadumu OTP_TTL_MINUTES, majaribio OTP_MAX_ATTEMPTS, na haihifadhiwi wazi (hash tu).
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .. import config
from ..core.base_model import utc_now
from ..core.exceptions import AppError, BadRequest, NotFound
from ..core.phone import try_normalize
from ..user.model import User


def _hash(user: User, code: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), f"{user.id}:{code}".encode(), hashlib.sha256).hexdigest()


def phone_hint(phone: str | None) -> str:
    p = try_normalize(phone) or ""
    return f"{p[:4]}*****{p[-3:]}" if len(p) >= 8 else ""


def challenge_token(user: User, kind: str = "otp") -> str:
    """kind: "otp" (kuingia kwa 2FA) au "reset" (kusahau nywila)."""
    claims = {"id": str(user.id), "sub": user.username, "ver": int(user.tokenVersion or 0), "type": kind,
              "cid": str(user.company_id),
              "exp": datetime.now(timezone.utc) + timedelta(minutes=max(config.OTP_TTL_MINUTES, 1) + 5)}
    return jwt.encode(claims, config.SECRET_KEY, algorithm=config.ALGORITHM)


def user_from_token(db: Session, token: str, kind: str = "otp") -> User:
    try:
        payload = jwt.decode(token or "", config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except JWTError:
        payload = {}
    from ..core import tenant

    if payload.get("type") != kind or not payload.get("id") or payload.get("cid") != str(tenant.company_id()):
        raise BadRequest("Muda wa kuingia umeisha - ingia upya / login session expired")
    user = db.get(User, __import__("uuid").UUID(payload["id"]))
    if user is None or int(user.tokenVersion or 0) != int(payload.get("ver") or 0) or user.active == 0:
        raise NotFound("Incorrect username or password")
    return user


def deliver(phone: str, text: str) -> None:
    """Inatuma SMS ya code moja kwa moja kwa gateway (tests zinaweza kuibadilisha)."""
    from ..sms.model import Sms
    from ..sms.service import _send_to_gateway

    # reference ya kipekee kwa kila code (gateway nyingine zinakataa reference inayojirudia)
    _send_to_gateway(Sms(text=text, msisdn=phone, source=config.SMS_SOURCE_NAME,
                         reference=f"OTP{secrets.token_hex(12).upper()}", coding=config.SMS_CODING, smsFor="CUSTOM"))


def send(db: Session, user: User, force: bool = False, purpose: str = "login") -> None:
    phone = try_normalize(user.phoneNumber)
    if not phone:
        raise BadRequest("Huna namba sahihi ya simu kwa code ya kuingia - wasiliana na msimamizi "
                         "/ no valid phone number for the login code")
    now = utc_now()
    if not force and user.otpSentAt and (now - user.otpSentAt).total_seconds() < config.OTP_RESEND_SECONDS:
        wait = int(config.OTP_RESEND_SECONDS - (now - user.otpSentAt).total_seconds())
        raise BadRequest(f"Subiri sekunde {wait} kabla ya kuomba code nyingine / wait {wait}s")
    code = f"{secrets.randbelow(1_000_000):06d}"
    user.otpHash = _hash(user, code)
    user.otpExpires = now + timedelta(minutes=max(config.OTP_TTL_MINUTES, 1))
    user.otpSentAt = now
    user.otpAttempts = 0
    db.commit()
    what = "ya kubadilisha nywila" if purpose == "reset" else "ya kuingia"
    text = (f"{config.COMPANY_NAME}: code yako {what} ni {code}. Inaisha baada ya dakika "
            f"{config.OTP_TTL_MINUTES}. Usimpe mtu yeyote.")
    try:
        deliver(phone, text)
    except AppError as error:
        # SMS haikutoka: mtumiaji aweze kujaribu tena mara moja (bila "subiri sekunde ...")
        user.otpHash = None
        user.otpExpires = None
        user.otpSentAt = None
        db.commit()
        raise AppError(f"Code haikutumwa: {error.detail} / the code could not be sent")


def verify(db: Session, user: User, code: str) -> None:
    now = utc_now()
    if not user.otpHash or not user.otpExpires or now > user.otpExpires:
        raise BadRequest("Code imeisha muda - omba nyingine / code expired")
    if (user.otpAttempts or 0) >= config.OTP_MAX_ATTEMPTS:
        raise BadRequest("Umekosea mara nyingi - omba code nyingine / too many attempts")
    if not hmac.compare_digest(user.otpHash, _hash(user, (code or "").strip())):
        user.otpAttempts = (user.otpAttempts or 0) + 1
        db.commit()
        left = max(config.OTP_MAX_ATTEMPTS - user.otpAttempts, 0)
        raise BadRequest(f"Code si sahihi. Majaribio yaliyobaki: {left} / wrong code")
    user.otpHash = None
    user.otpExpires = None
    user.otpAttempts = 0
    db.commit()
