"""
TOTP (RFC 6238) - code za tarakimu 6 za app ya uthibitisho (Google Authenticator, Microsoft Authenticator,
Authy ...). Bila maktaba ya ziada.

    secret = totp.new_secret()
    uri = totp.uri(secret, "superadmin", "Logistic Cloud")   # QR ya kuskani kwenye app
    totp.verify(secret, "123456")                           # True / False (inakubali dakika ±1)
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
PERIOD = 30


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, counter: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def now(secret: str, at: float | None = None) -> str:
    return code_at(secret, int((at if at is not None else time.time()) // PERIOD))


def verify(secret: str | None, code: str | None, window: int = 1, at: float | None = None) -> int | None:
    """Inarudisha counter ya code iliyokubaliwa (kuzuia kutumia code ile ile mara mbili), au None."""
    code = "".join(c for c in (code or "") if c.isdigit())
    if not secret or len(code) != DIGITS:
        return None
    counter = int((at if at is not None else time.time()) // PERIOD)
    for step in range(-window, window + 1):
        if hmac.compare_digest(code_at(secret, counter + step), code):
            return counter + step
    return None


def uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"


def recovery_codes(n: int = 10) -> list[str]:
    """Code za dharura (simu ikipotea): kila moja inatumika mara moja tu."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2)) for _ in range(n)]


def hash_recovery(code: str, salt: str) -> str:
    clean = "".join(c for c in (code or "").upper() if c.isalnum())
    return hmac.new(salt.encode(), clean.encode(), hashlib.sha256).hexdigest()
