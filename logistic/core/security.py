"""
Ulinzi: kuhash nywila na JWT token.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from .. import config

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")


class TokenData(BaseModel):
    id: UUID
    username: str | None = None
    ver: int = 0
    mustChangePassword: bool = False
    cid: UUID | None = None  # kampuni ya mtumiaji
    imp: str | None = None   # super admin anayeangalia kama mtumiaji huyu (kuangalia tu)


def password_problem(password: str) -> str | None:
    """Sera ya nywila: angalau herufi 8, zenye herufi na namba."""
    if len(password or "") < config.PASSWORD_MIN_LENGTH:
        return f"Password must be at least {config.PASSWORD_MIN_LENGTH} characters"
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Password must contain both letters and numbers"
    return None


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    to_encode["type"] = "access"
    to_encode["exp"] = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES))
    return jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode["type"] = "refresh"
    to_encode["exp"] = datetime.now(timezone.utc) + timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)


def decode_refresh_token(token: str) -> TokenData | None:
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "refresh" or not payload.get("id"):
        return None
    try:
        return TokenData(id=payload["id"], username=payload.get("sub"), ver=int(payload.get("ver") or 0),
                         cid=payload.get("cid"))
    except ValueError:
        return None


def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        user_id = payload.get("id")
        username = payload.get("sub")
        # refresh token (na token ya platform admin) haitumiki kama access token ya kampuni
        if user_id is None or username is None or payload.get("type") != "access":
            raise credentials_exception
        token = TokenData(id=user_id, username=username, ver=int(payload.get("ver") or 0), cid=payload.get("cid"),
                          imp=payload.get("imp"))
    except (JWTError, ValueError):
        raise credentials_exception
    from . import tenant

    # token ya kampuni moja haitumiki kwenye kampuni nyingine
    if token.cid is None or token.cid != tenant.company_id():
        raise credentials_exception
    if not _session_valid(token):
        raise credentials_exception
    if token.imp:
        token.mustChangePassword = False  # super admin anaangalia tu - asisimamishwe na skrini ya nywila
    return token


def _session_valid(token: TokenData) -> bool:
    # (query hii inachujwa kwa kampuni ya request: mtumiaji wa kampuni nyingine "hayupo")
    """Mtumiaji bado yupo, hajazuiwa, na token haijafutwa (toa kwenye vifaa vyote / nywila mpya)."""
    from ..db import SessionLocal
    from ..user.model import User

    db = SessionLocal()
    try:
        row = (db.query(User.active, User.tokenVersion, User.mustChangePassword)
               .filter(User.id == token.id).one_or_none())
    finally:
        db.close()
    if row is None or row[0] == 0 or int(row[1] or 0) != token.ver:
        return False
    token.mustChangePassword = bool(row[2])
    return True
