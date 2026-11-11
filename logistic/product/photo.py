"""
Picha ya mzigo kwa simu kupitia QR ya code ya ofisi.

Web inaonyesha QR yenye code ya ofisi; app ya simu inaiskani, inapiga picha na kuipakia hapa:
  - mzigo wenye code hiyo upo  -> picha inawekwa kwenye mzigo huo moja kwa moja (ya zamani inafutwa);
  - bado haujahifadhiwa (fomu ya kusajili iko wazi kwenye web) -> picha inasubiri (staged) na inaunganishwa
    na mzigo ukihifadhiwa. Picha zinazosubiri zaidi ya saa 24 zinafutwa.
"""
import os
import time
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core import files, office_code
from ..core.exceptions import BadRequest, NotFound
from .model import Product

STAGED_HOURS = 24


def _dir() -> str:
    """Folder la picha zinazosubiri - la kampuni hii tu (code za ofisi zinaweza kufanana kati ya kampuni)."""
    return files.tenant_dir("Staged")


def find(db: Session, code: str) -> Product | None:
    key = office_code.key(code)
    if not key:
        return None
    return db.query(Product).filter(func.replace(func.upper(Product.officeCode), "-", "") == key).first()


def _key(code: str) -> str:
    if office_code.clean(code) is None:  # BadRequest kama muundo si sahihi
        raise BadRequest("Weka code ya ofisi")
    return office_code.key(code)


def _staged(code: str) -> Path | None:
    folder = files.absolute(_dir())
    if not folder.is_dir():
        return None
    key = _key(code)
    for ext in files.ALLOWED_IMAGE_EXT:
        path = folder / f"{key}{ext}"
        if path.is_file():
            return path
    return None


def _clear_staged(code: str) -> None:
    path = _staged(code)
    while path is not None:
        path.unlink(missing_ok=True)
        path = _staged(code)


def upload(db: Session, code: str, filename: str | None, content: bytes) -> dict:
    if not content:
        raise BadRequest("Hakuna picha")
    ext = os.path.splitext(filename or "")[1].lower() or ".jpg"
    if ext not in files.ALLOWED_IMAGE_EXT:
        raise BadRequest("Only JPG, JPEG and PNG files are supported")
    product = find(db, code)
    if product is not None:
        old = product.path
        product.path = files.save_image(f"photo{ext}", content)
        db.commit()
        if old and old != product.path:
            files.remove(old)
        _clear_staged(code)
        invoice = product.invoice[0] if isinstance(product.invoice, list) and product.invoice else product.invoice
        return {"attached": True, "productId": str(product.id), "description": product.description,
                "officeCode": product.officeCode,
                "invoiceNumber": getattr(invoice, "invoiceNumber", None)}
    key = _key(code)
    _clear_staged(code)
    files.ensure_dir(_dir())
    files.absolute(f"{_dir()}/{key}{ext}").write_bytes(content)
    return {"attached": False, "staged": True, "officeCode": key}


def status(db: Session, code: str) -> dict:
    product = find(db, code)
    if product is not None:
        return {"exists": True, "productId": str(product.id), "path": product.path, "staged": False}
    path = _staged(code)
    return {"exists": False, "path": None, "staged": path is not None,
            "stagedAt": int(path.stat().st_mtime) if path else None}


def discard_staged(code: str) -> bool:
    """Mtumiaji ameondoa picha ya simu kwenye fomu kabla ya kuhifadhi."""
    _clear_staged(code)
    return True


def staged_file(code: str) -> Path:
    path = _staged(code)
    if path is None:
        raise NotFound("Hakuna picha inayosubiri")
    return path


def attach_staged(db: Session, product: Product) -> bool:
    """Mzigo mpya: picha iliyopigwa kwa simu kabla ya kuhifadhi inaunganishwa nao."""
    if product.path or not product.officeCode:
        return False
    path = _staged(product.officeCode)
    if path is None:
        return False
    product.path = files.save_image(f"photo{path.suffix}", path.read_bytes())
    db.commit()
    path.unlink(missing_ok=True)
    return True


def cleanup_staged(hours: int = STAGED_HOURS) -> int:
    folder = files.absolute(_dir())
    if not folder.is_dir():
        return 0
    cutoff, removed = time.time() - hours * 3600, 0
    for path in folder.iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed
