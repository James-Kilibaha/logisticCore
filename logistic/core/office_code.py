"""
Code ya ofisi ya kila mzigo (bidhaa) uliosajiliwa.

Inatengenezwa mzigo unapopokelewa (au mtumiaji anaandika yake), inatumwa kwa mteja kwenye SMS, inachapishwa
kwenye lebo inayobandikwa kwenye box kabla ya kusafirishwa, na mpokeaji anaionyesha ofisini ili akabidhiwe
mzigo huo. Herufi zinazochanganya (0/O, 1/I/L) haziko ili isomeke vizuri kwenye simu na lebo.
"""
import re
import secrets

from sqlalchemy.orm import Session

from .exceptions import BadRequest, Conflict

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LENGTH = 6
_VALID = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,18}[A-Z0-9]$")


def key(value: str | None) -> str:
    """Kulinganisha: herufi kubwa, bila nafasi wala vistari."""
    return re.sub(r"[\s-]", "", (value or "").upper())


def clean(raw: str | None) -> str | None:
    """Code iliyoandikwa na mtumiaji -> muundo wa kuhifadhi (au BadRequest kama si sahihi)."""
    value = re.sub(r"\s+", "", (raw or "").upper())
    if not value:
        return None
    if not _VALID.match(value):
        raise BadRequest("Code ya ofisi: herufi na namba 4 hadi 20 tu (A-Z, 0-9, -)")
    return value


def split(raw: str | list[str] | None) -> set[str]:
    """Code kadhaa zilizoandikwa/skaniwa pamoja (koma, nafasi au mstari mpya) -> seti ya funguo."""
    parts = raw if isinstance(raw, list) else re.split(r"[,;\s]+", raw or "")
    return {key(p) for p in parts if key(p)}


def taken(db: Session, code: str, except_product_id=None) -> bool:
    from ..product.model import Product

    q = db.query(Product.id).filter(Product.officeCode == code)
    if except_product_id is not None:
        q = q.filter(Product.id != except_product_id)
    return q.first() is not None


def generate(db: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
        if not taken(db, code):
            return code
    raise Conflict("Imeshindikana kutengeneza code ya ofisi, jaribu tena")


def for_new_product(db: Session, raw: str | None) -> str:
    """Code ya mzigo mpya: aliyoandika mtumiaji (mf. lebo iliyochapishwa tayari) au mpya ya mfumo."""
    code = clean(raw)
    if code is None:
        return generate(db)
    if taken(db, code):
        raise Conflict(f"Code {code} inatumika kwenye mzigo mwingine")
    return code
