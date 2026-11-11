"""
Platform admin (wewe): kuingia, wasaidizi, na takwimu za mfumo mzima (dashboard ya admin panel).
Token ya platform ina `type=platform` - haitumiki kwenye API za kampuni, na token za kampuni hazitumiki hapa.
"""
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import config
from ...core import audit, ratelimit
from ...core.base_model import utc_now
from ...core.exceptions import BadRequest, Conflict, NotFound
from ...core.security import hash_password, password_problem, verify_password
from . import schema
from .dao import PlatformAdminDao
from .model import PlatformAdmin

# /api/platform/token: fomu ya "Authorize" kwenye /docs (Swagger)
_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/platform/token", scheme_name="PlatformAdmin")


def _token(admin: PlatformAdmin) -> schema.LoginResponse:
    minutes = max(config.ACCESS_TOKEN_EXPIRE_MINUTES, 60) * 4
    claims = {"pid": str(admin.id), "sub": admin.username, "ver": int(admin.tokenVersion or 0), "type": "platform",
              "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes)}
    return schema.LoginResponse(access_token=jwt.encode(claims, config.SECRET_KEY, algorithm=config.ALGORITHM),
                                expires_in=minutes * 60, admin=schema.AdminOut.model_validate(admin))


def current_admin(token: str = Depends(_oauth2)) -> PlatformAdmin:
    """Dependency ya endpoints zote za /api/platform."""
    from ...db import SessionLocal

    error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials",
                          headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except JWTError:
        raise error
    if payload.get("type") != "platform" or not payload.get("pid"):
        raise error
    db = SessionLocal()
    try:
        admin = PlatformAdminDao(db).get(payload["pid"])
    finally:
        db.close()
    if admin is None or not admin.active or int(admin.tokenVersion or 0) != int(payload.get("ver") or 0):
        raise error
    return admin


def login(db: Session, data: schema.Login, ip: str | None) -> schema.LoginResponse:
    username = data.username.strip()
    key = f"platform:{username.lower()}"
    ratelimit.check(key, ip)
    admin = PlatformAdminDao(db).by_username(username)
    if admin is None or not admin.active or not verify_password(data.password, admin.password):
        ratelimit.failed(key, ip)
        audit.write(user_id=admin.id if admin else None, username=username[:100], module="platform", action="LOGIN",
                    method="POST", path="/api/platform/login", entity_id=None, status_code=401, ip=ip,
                    summary="Platform admin: nywila au jina si sahihi", detail=None)
        from ..audit_log import record

        record(admin, "LOGIN_FAILED", f"Kuingia kumeshindwa ({username[:60]})", ip=ip, status_code=401)
        raise NotFound("Incorrect username or password")
    if admin.totpEnabled and admin.totpSecret:
        # nywila sahihi - sasa code ya app (hatua ya pili)
        claims = {"pid": str(admin.id), "ver": int(admin.tokenVersion or 0), "type": "platform-2fa",
                  "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
        return schema.LoginResponse(twoFactorRequired=True,
                                    challenge=jwt.encode(claims, config.SECRET_KEY, algorithm=config.ALGORITHM))
    ratelimit.succeeded(key)
    return _finish_login(db, admin, ip, "Platform admin: ameingia")


def _finish_login(db: Session, admin: PlatformAdmin, ip: str | None, summary: str) -> schema.LoginResponse:
    from ..audit_log import record

    admin.lastLoginAt = utc_now()
    db.commit()
    db.refresh(admin)
    record(admin, "LOGIN", summary, ip=ip)
    return _token(admin)


# ------------------------------------------------------------------ uthibitisho wa hatua mbili (TOTP)

def _check_code(db: Session, admin: PlatformAdmin, code: str) -> str | None:
    """'app' (code ya Authenticator) / 'recovery' (code ya dharura - inafutwa) / None."""
    from ...core import totp

    counter = totp.verify(admin.totpSecret, code)
    if counter is not None:
        if admin.totpLastCounter is not None and counter <= admin.totpLastCounter:
            return None  # code ile ile haitumiki mara mbili
        admin.totpLastCounter = counter
        return "app"
    hashed = totp.hash_recovery(code, f"{config.SECRET_KEY}:{admin.id}")
    left = list(admin.totpRecovery or [])
    if hashed in left:
        left.remove(hashed)
        admin.totpRecovery = left
        return "recovery"
    return None


def login_2fa(db: Session, data: schema.TwoFactorLogin, ip: str | None) -> schema.LoginResponse:
    from ..audit_log import record

    try:
        payload = jwt.decode(data.challenge, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except JWTError:
        payload = {}
    admin = PlatformAdminDao(db).get(payload.get("pid")) if payload.get("type") == "platform-2fa" else None
    if admin is None or not admin.active or int(admin.tokenVersion or 0) != int(payload.get("ver") or 0):
        raise BadRequest("Muda wa kuingia umeisha - anza upya / login expired, start again")
    key = f"platform-2fa:{admin.username.lower()}"
    ratelimit.check(key, ip)
    how = _check_code(db, admin, data.code)
    if how is None:
        db.commit()
        ratelimit.failed(key, ip)
        record(admin, "LOGIN_2FA_FAILED", "Code ya 2FA si sahihi", ip=ip, status_code=401)
        raise BadRequest("Code si sahihi / wrong code")
    ratelimit.succeeded(key)
    ratelimit.succeeded(f"platform:{admin.username.lower()}")
    left = len(admin.totpRecovery or [])
    note = f" (code ya dharura - zimebaki {left})" if how == "recovery" else ""
    return _finish_login(db, admin, ip, f"Platform admin: ameingia kwa 2FA{note}")


def two_factor_status(admin: PlatformAdmin) -> dict:
    return {"enabled": bool(admin.totpEnabled), "recoveryLeft": len(admin.totpRecovery or [])}


def two_factor_setup(db: Session, admin_id) -> dict:
    """Hatua ya 1: siri mpya + QR (otpauth://) ya kuskani kwenye app. Haiwashwi mpaka code ithibitishwe."""
    from ...core import totp

    admin = PlatformAdminDao(db).get(admin_id)
    admin.totpPendingSecret = totp.new_secret()
    db.commit()
    return {"secret": admin.totpPendingSecret,
            "uri": totp.uri(admin.totpPendingSecret, admin.username, config.PLATFORM_NAME)}


def _new_recovery(admin: PlatformAdmin) -> list[str]:
    from ...core import totp

    codes = totp.recovery_codes()
    admin.totpRecovery = [totp.hash_recovery(c, f"{config.SECRET_KEY}:{admin.id}") for c in codes]
    return codes


def two_factor_enable(db: Session, admin_id, data: schema.TwoFactorCode, ip: str | None) -> dict:
    """Hatua ya 2: code ya app inathibitisha - 2FA inawashwa; code 10 za dharura zinaonyeshwa MARA MOJA."""
    from ...core import totp
    from ..audit_log import record

    admin = PlatformAdminDao(db).get(admin_id)
    if not admin.totpPendingSecret:
        raise BadRequest("Anza kwa kuskani QR / start the setup first")
    counter = totp.verify(admin.totpPendingSecret, data.code)
    if counter is None:
        raise BadRequest("Code si sahihi - hakikisha saa ya simu iko sawa / wrong code")
    admin.totpSecret = admin.totpPendingSecret
    admin.totpPendingSecret = None
    admin.totpEnabled = True
    admin.totpLastCounter = counter
    codes = _new_recovery(admin)
    db.commit()
    record(admin, "2FA_ENABLED", "Amewasha uthibitisho wa hatua mbili", ip=ip)
    return {"enabled": True, "recoveryCodes": codes}


def _confirm(db: Session, admin: PlatformAdmin, data: schema.TwoFactorConfirm) -> None:
    if not verify_password(data.password, admin.password):
        raise BadRequest("Nywila si sahihi / wrong password")
    if not admin.totpEnabled or _check_code(db, admin, data.code) is None:
        db.commit()
        raise BadRequest("Code si sahihi / wrong code")


def two_factor_disable(db: Session, admin_id, data: schema.TwoFactorConfirm, ip: str | None) -> dict:
    from ..audit_log import record

    admin = PlatformAdminDao(db).get(admin_id)
    _confirm(db, admin, data)
    admin.totpEnabled = False
    admin.totpSecret = None
    admin.totpRecovery = None
    admin.totpLastCounter = None
    db.commit()
    record(admin, "2FA_DISABLED", "Amezima uthibitisho wa hatua mbili", ip=ip)
    return {"enabled": False}


def two_factor_new_recovery(db: Session, admin_id, data: schema.TwoFactorConfirm, ip: str | None) -> dict:
    from ..audit_log import record

    admin = PlatformAdminDao(db).get(admin_id)
    _confirm(db, admin, data)
    codes = _new_recovery(admin)
    db.commit()
    record(admin, "2FA_RECOVERY", "Ametengeneza code mpya za dharura", ip=ip)
    return {"recoveryCodes": codes}


def reset_two_factor(db: Session, target_id, by: PlatformAdmin, ip: str | None) -> dict:
    """Msimamizi mwingine ameipoteza simu: 2FA yake inaondolewa (ataiwasha upya akiingia)."""
    from ..audit_log import record

    admin = PlatformAdminDao(db).get(target_id)
    if admin is None:
        raise NotFound("Admin not found")
    if str(admin.id) == str(by.id):
        raise BadRequest("Tumia 'Zima 2FA' kwa akaunti yako mwenyewe")
    admin.totpEnabled = False
    admin.totpSecret = None
    admin.totpRecovery = None
    admin.totpLastCounter = None
    admin.tokenVersion = int(admin.tokenVersion or 0) + 1
    db.commit()
    record(by, "2FA_RESET", f"Ameondoa 2FA ya {admin.username}", ip=ip)
    return {"ok": True}


def change_password(db: Session, admin_id, data: schema.ChangePassword) -> schema.LoginResponse:
    admin = PlatformAdminDao(db).get(admin_id)
    if admin is None or not verify_password(data.oldPassword, admin.password):
        raise BadRequest("Current password is not correct")
    problem = password_problem(data.newPassword)
    if problem:
        raise BadRequest(problem)
    admin.password = hash_password(data.newPassword)
    admin.tokenVersion = int(admin.tokenVersion or 0) + 1
    db.commit()
    db.refresh(admin)
    return _token(admin)


# ------------------------------------------------------------------ kusahau nywila

def _otp_hash(admin: PlatformAdmin, code: str) -> str:
    import hashlib
    import hmac

    return hmac.new(config.SECRET_KEY.encode(), f"platform:{admin.id}:{code}".encode(), hashlib.sha256).hexdigest()


def _mask_phone(phone: str) -> str:
    return f"{phone[:4]}*****{phone[-3:]}" if len(phone) >= 8 else ""


def _mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}"


def deliver_code(phone: str | None, email: str | None, text: str) -> list[str]:
    """Inatuma code kwa SMS (akaunti yako ya .env) na/au email. Inarudisha njia zilizofanikiwa (tests zinaibadilisha)."""
    import secrets as _secrets

    from ...core import mail

    sent = []
    if phone and config.SMS_CLIENT_ID and config.SMS_CLIENT_SECRET:
        from ...sms.model import Sms
        from ...sms.service import _send_to_gateway

        try:
            _send_to_gateway(Sms(text=text, msisdn=phone, source=config.PLATFORM_SMS_SOURCE or config.SMS_SOURCE_NAME,
                                 reference=f"POTP{_secrets.token_hex(11).upper()}", coding=config.SMS_CODING,
                                 smsFor="CUSTOM"))
            sent.append(f"SMS {_mask_phone(phone)}")
        except Exception:
            pass
    if email and mail.send(email, f"{config.PLATFORM_NAME}: code ya kubadilisha nywila", text):
        sent.append(f"email {_mask_email(email)}")
    return sent


def forgot(db: Session, data: schema.Forgot, ip: str | None) -> dict:
    """
    Super admin amesahau nywila, hatua ya 1: code inatumwa kwa SMS (simu yake) na email yake.
    Kama hana simu/email au SMS na SMTP hazijawekwa: tumia terminal (python -m logistic.saas.admin password ...).
    """
    import secrets as _secrets

    from ...core.phone import try_normalize

    value = data.username.strip()
    ratelimit.hit(f"platform-forgot:{ip or '-'}", limit=10, window_seconds=900)
    ratelimit.hit(f"platform-forgot-user:{value.lower()}", limit=5, window_seconds=900)
    dao = PlatformAdminDao(db)
    admin = dao.by_username(value)
    if admin is None:
        phone = try_normalize(value) if "@" not in value else None
        for a in dao.ordered():
            if (phone and try_normalize(a.phone) == phone) or ("@" in value and (a.email or "").lower() == value.lower()):
                admin = a
                break
    if admin is None or not admin.active:
        raise BadRequest("Hakuna super admin mwenye jina, simu au email hii / no such admin")
    now = utc_now()
    if admin.otpSentAt and (now - admin.otpSentAt).total_seconds() < config.OTP_RESEND_SECONDS:
        wait = int(config.OTP_RESEND_SECONDS - (now - admin.otpSentAt).total_seconds())
        raise BadRequest(f"Subiri sekunde {wait} kabla ya kuomba code nyingine / wait {wait}s")
    code = f"{_secrets.randbelow(1_000_000):06d}"
    text = (f"{config.PLATFORM_NAME}: code yako ya kubadilisha nywila ni {code}. Inaisha baada ya dakika "
            f"{config.OTP_TTL_MINUTES}. Usimpe mtu yeyote.")
    channels = deliver_code(try_normalize(admin.phone), admin.email, text)
    audit.write(user_id=admin.id, username=admin.username, module="platform", action="PASSWORD_FORGOT",
                method="POST", path="/api/platform/forgot", entity_id=None, status_code=200 if channels else 400,
                ip=ip, summary="Platform admin: ameomba code ya nywila", detail=", ".join(channels) or None)
    if not channels:
        raise BadRequest("Code haikuweza kutumwa: hakikisha una simu/email kwenye akaunti yako na SMS au SMTP "
                         "imewekwa kwenye .env. Vinginevyo badilisha nywila kwenye server: "
                         f"python -m logistic.saas.admin password {admin.username} <nywila_mpya>")
    admin.otpHash = _otp_hash(admin, code)
    admin.otpExpires = now + timedelta(minutes=max(config.OTP_TTL_MINUTES, 1))
    admin.otpSentAt = now
    admin.otpAttempts = 0
    db.commit()
    claims = {"pid": str(admin.id), "ver": int(admin.tokenVersion or 0), "type": "platform-reset",
              "exp": datetime.now(timezone.utc) + timedelta(minutes=max(config.OTP_TTL_MINUTES, 1) + 5)}
    return {"resetToken": jwt.encode(claims, config.SECRET_KEY, algorithm=config.ALGORITHM),
            "sentTo": channels, "username": admin.username, "ttlMinutes": config.OTP_TTL_MINUTES}


def forgot_reset(db: Session, data: schema.ForgotReset, ip: str | None) -> dict:
    import hmac

    ratelimit.hit(f"platform-forgot-reset:{ip or '-'}", limit=20, window_seconds=900)
    try:
        payload = jwt.decode(data.resetToken, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except JWTError:
        payload = {}
    admin = PlatformAdminDao(db).get(payload.get("pid")) if payload.get("type") == "platform-reset" else None
    if admin is None or not admin.active or int(admin.tokenVersion or 0) != int(payload.get("ver") or 0):
        raise BadRequest("Muda umeisha - omba code upya / request a new code")
    problem = password_problem(data.newPassword)
    if problem:
        raise BadRequest(problem)
    now = utc_now()
    if not admin.otpHash or not admin.otpExpires or now > admin.otpExpires:
        raise BadRequest("Code imeisha muda - omba nyingine / code expired")
    if (admin.otpAttempts or 0) >= config.OTP_MAX_ATTEMPTS:
        raise BadRequest("Umekosea mara nyingi - omba code nyingine / too many attempts")
    if not hmac.compare_digest(admin.otpHash, _otp_hash(admin, data.code.strip())):
        admin.otpAttempts = (admin.otpAttempts or 0) + 1
        db.commit()
        left = max(config.OTP_MAX_ATTEMPTS - admin.otpAttempts, 0)
        raise BadRequest(f"Code si sahihi. Majaribio yaliyobaki: {left} / wrong code")
    admin.password = hash_password(data.newPassword)
    admin.tokenVersion = int(admin.tokenVersion or 0) + 1
    admin.otpHash = None
    admin.otpExpires = None
    admin.otpAttempts = 0
    db.commit()
    ratelimit.succeeded(f"platform:{admin.username.lower()}")
    audit.write(user_id=admin.id, username=admin.username, module="platform", action="PASSWORD_RESET",
                method="POST", path="/api/platform/forgot/reset", entity_id=None, status_code=200, ip=ip,
                summary="Platform admin: amebadilisha nywila kwa code", detail=None)
    return {"ok": True, "username": admin.username}


def list_admins(db: Session) -> list[PlatformAdmin]:
    return PlatformAdminDao(db).ordered()


def create_admin(db: Session, data: schema.AdminCreate) -> PlatformAdmin:
    dao = PlatformAdminDao(db)
    if dao.by_username(data.username):
        raise Conflict("Jina hili la mtumiaji lipo tayari")
    problem = password_problem(data.password)
    if problem:
        raise BadRequest(problem)
    from .roles import check

    return dao.create(username=data.username.strip(), password=hash_password(data.password),
                      fullName=data.fullName.strip(), phone=data.phone, email=data.email, active=True,
                      role=check(data.role))


def update_admin(db: Session, data: schema.AdminUpdate, me_id) -> PlatformAdmin:
    dao = PlatformAdminDao(db)
    admin = dao.get(data.id)
    if admin is None:
        raise NotFound("Msimamizi hayupo")
    if admin.id == me_id and not data.active:
        raise BadRequest("Huwezi kujizuia mwenyewe")
    from .roles import check

    new_role = check(data.role) if data.role else (admin.role or "OWNER")
    if (admin.role or "OWNER") == "OWNER" and (new_role != "OWNER" or not data.active):
        owners = [a for a in dao.ordered() if a.active and (a.role or "OWNER") == "OWNER" and a.id != admin.id]
        if not owners:
            raise BadRequest("Lazima abaki angalau OWNER mmoja aliye hai / at least one active OWNER is required")
    if new_role != (admin.role or "OWNER"):
        admin.role = new_role
        admin.tokenVersion = int(admin.tokenVersion or 0) + 1
    admin.fullName, admin.phone, admin.email = data.fullName.strip(), data.phone, data.email
    if admin.active != data.active:
        admin.active = data.active
        admin.tokenVersion = int(admin.tokenVersion or 0) + 1
    if data.password:
        problem = password_problem(data.password)
        if problem:
            raise BadRequest(problem)
        admin.password = hash_password(data.password)
        admin.tokenVersion = int(admin.tokenVersion or 0) + 1
    db.commit()
    db.refresh(admin)
    return admin


def seed_from_env(db: Session) -> None:
    """Msimamizi wa kwanza wa platform kutoka `.env` (ADMIN_USERNAME/ADMIN_PASSWORD) kama hakuna yeyote."""
    import logging

    log = logging.getLogger(__name__)
    dao = PlatformAdminDao(db)
    if dao.count() > 0:
        return
    if not (config.ADMIN_USERNAME and config.ADMIN_PASSWORD):
        log.warning("HAKUNA SUPER ADMIN: weka ADMIN_USERNAME na ADMIN_PASSWORD kwenye .env na uwashe server upya, "
                    "au endesha:  python -m logistic.saas.admin create <username> <password>")
        return
    problem = password_problem(config.ADMIN_PASSWORD)
    if problem:
        log.warning("Super admin HAJAUNDWA - ADMIN_PASSWORD ya .env haikubaliki: %s", problem)
        return
    dao.create(username=config.ADMIN_USERNAME.strip(), password=hash_password(config.ADMIN_PASSWORD),
               fullName=f"{config.ADMIN_FIRST_NAME} {config.ADMIN_LAST_NAME}".strip(), phone=config.ADMIN_PHONE,
               active=True)
    log.info("Super admin '%s' ameundwa kutoka .env", config.ADMIN_USERNAME)


def reset_tenant_password(db: Session, company_id, data: schema.ResetTenantPassword) -> dict:
    from ...core import tenant
    from ...db import SessionLocal
    from ...user.dao import UserDao

    problem = password_problem(data.newPassword)
    if problem:
        raise BadRequest(problem)
    with tenant.use_company(company_id):
        tdb = SessionLocal()
        try:
            user = UserDao(tdb).by_username(data.username.strip())
            if user is None:
                raise NotFound("Mtumiaji hayupo kwenye kampuni hii")
            user.password = hash_password(data.newPassword)
            user.mustChangePassword = True
            user.active = 1
            user.tokenVersion = int(user.tokenVersion or 0) + 1
            user.otpAttempts = 0
            tdb.commit()
            ratelimit.succeeded(user.username)
        finally:
            tdb.close()
    return {"ok": True, "username": data.username.strip()}


def tenant_users(db: Session, company_id) -> list[dict]:
    from ...user.model import User

    rows = (db.query(User).filter(User.company_id == company_id).order_by(User.firstName).all())
    return [{"id": str(u.id), "username": u.username, "name": f"{u.firstName} {u.lastName}",
             "phone": u.phoneNumber, "active": bool(u.active), "created_at": u.created_at} for u in rows]


def dashboard(db: Session) -> dict:
    """Takwimu za admin panel yako: kampuni, subscription, mapato."""
    from ..company.model import Company
    from ..subscription import service as subscriptions
    from ..subscription.model import SubscriptionPayment

    companies = db.query(Company).all()
    counts = {"total": len(companies), "active": 0, "suspended": 0, "pending": 0, "rejected": 0, "trial": 0,
              "paying": 0, "grace": 0, "expired": 0, "none": 0, "expiringSoon": 0}
    awaiting = []
    expiring = []
    mrr = 0.0
    for company in companies:
        if company.status == "SUSPENDED":
            counts["suspended"] += 1
            continue
        if company.status == "REJECTED":
            counts["rejected"] += 1
            continue
        if company.status == "PENDING":
            counts["pending"] += 1
            awaiting.append({"id": str(company.id), "name": company.name, "slug": company.slug,
                             "phone": company.phone, "ownerName": company.ownerName,
                             "created_at": company.created_at.isoformat() if company.created_at else None})
            continue
        counts["active"] += 1
        st = subscriptions.compute(db, company.id)
        key = {"TRIAL": "trial", "ACTIVE": "paying", "GRACE": "grace", "EXPIRED": "expired"}.get(st["status"], "none")
        counts[key] += 1
        if st["status"] == "ACTIVE" and st["plan"]:
            mrr += float(st["plan"]["price"] or 0) / max(int(st["plan"]["months"] or 1), 1)
        if st["status"] in ("TRIAL", "ACTIVE", "GRACE") and st["daysLeft"] is not None and st["daysLeft"] <= 7:
            counts["expiringSoon"] += 1
            expiring.append({"id": str(company.id), "name": company.name, "slug": company.slug,
                             "status": st["status"], "endsAt": st["endsAt"], "daysLeft": st["daysLeft"]})
    month_start = utc_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    revenue = (db.query(SubscriptionPayment.currency, func.sum(SubscriptionPayment.amount))
               .filter(SubscriptionPayment.status == "CONFIRMED", SubscriptionPayment.reviewedAt >= month_start)
               .group_by(SubscriptionPayment.currency).all())
    pending = db.query(func.count(SubscriptionPayment.id)).filter(SubscriptionPayment.status == "PENDING").scalar()
    since = utc_now() - timedelta(days=30)
    new_companies = sum(1 for c in companies if c.created_at and c.created_at >= since)
    return {
        "companies": counts,
        "newCompanies30d": new_companies,
        "pendingPayments": int(pending or 0),
        "revenueThisMonth": [{"currency": c, "amount": float(a or 0)} for c, a in revenue],
        "mrrTzs": round(mrr),
        "expiring": sorted(expiring, key=lambda r: r["daysLeft"]),
        "awaitingApproval": sorted(awaiting, key=lambda r: r["created_at"] or "", reverse=True),
        # salio la akaunti yako ya FastHub (kutoka jibu la mwisho la kutuma SMS) - kampuni hazilioni
        "platformSmsBalance": _platform_sms(),
        "tickets": _tickets(db),
    }


def _tickets(db: Session) -> dict:
    from ..support.service import admin_counts

    return admin_counts(db)


def _platform_sms() -> dict:
    from ...sms.credit import platform_balance

    value, at = platform_balance()
    return {"balance": value, "seenAt": at, "lowAt": config.SMS_LOW_BALANCE}
