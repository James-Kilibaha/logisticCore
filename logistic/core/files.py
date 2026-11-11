"""
Mafaili (picha za bidhaa, PDF za invoice na ripoti).

Database inahifadhi njia fupi (mfano `<company_id>/Images/abc.jpg`); hapa tunaiunganisha
na `FILES_DIR` kutoka `.env`. Kila kampuni ina folder lake (jina = company_id).
"""
import os
import uuid
from pathlib import Path

from .. import config
from .exceptions import BadRequest, NotFound

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png"}

# files.IMAGES_DIR, files.INVOICE_DIR ... = folda za kampuni ya request ya sasa
_TENANT_DIRS = {
    "IMAGES_DIR": "Images",
    "INVOICE_DIR": "Report/Invoice",
    "REPORT_DIR": "Report",
    "HANDOVER_DIR": "Handover",
    "CLAIMS_DIR": "Claims",
}


def tenant_root() -> str:
    from . import tenant

    cid = tenant.company_id()
    return str(cid) if cid else "_system"


def tenant_dir(sub: str) -> str:
    return f"{tenant_root()}/{sub}"


def __getattr__(name: str):
    if name in _TENANT_DIRS:
        return tenant_dir(_TENANT_DIRS[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def owned(relative: str | None) -> bool:
    """Faili ni la kampuni ya sasa (njia inaanza na folder lake)."""
    return bool(relative) and str(relative).replace("\\", "/").split("/")[0] == tenant_root()


def absolute(relative: str) -> Path:
    """Njia kamili ndani ya FILES_DIR; inazuia njia zinazotoka nje (../)."""
    root = config.FILES_DIR.resolve()
    path = (root / relative).resolve()
    if root != path and root not in path.parents:
        raise BadRequest("Invalid file path")
    return path


def ensure_dir(relative_dir: str) -> Path:
    path = absolute(relative_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_image(filename: str, content: bytes, directory: str | None = None) -> str:
    directory = directory or tenant_dir("Images")
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise BadRequest("Only JPG, JPEG and PNG files are supported")
    ensure_dir(directory)
    relative = f"{directory}/{uuid.uuid4()}{ext}"
    absolute(relative).write_bytes(content)
    return relative


def remove(relative: str | None) -> bool:
    """Inafuta faili; inarudisha True kama faili halipo tena."""
    if not relative:
        return True
    path = absolute(relative)
    if path.exists():
        path.unlink()
    return not path.exists()


def existing(relative: str) -> Path:
    path = absolute(relative)
    if not path.is_file():
        raise NotFound("File not found")
    return path
