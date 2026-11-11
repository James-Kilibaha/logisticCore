"""Logo na rangi ya kampuni ya sasa kwa PDF (ankara, risiti, lebo, ripoti).

Logo ni ile kampuni iliyopakia (Kampuni > Logo). Ikikosekana au ikiharibika, PDF inaendelea bila logo.
"""
from __future__ import annotations

import logging
import threading

from reportlab.lib import colors
from reportlab.lib.utils import ImageReader

from . import tenant

logger = logging.getLogger(__name__)

DEFAULT = colors.HexColor("#1F4FD8")

_lock = threading.Lock()
_images: dict[tuple[str, float], ImageReader] = {}


def _value(name: str) -> str:
    cid = tenant.company_id()
    if cid is None:
        return ""
    from ..saas.company import settings as company_settings

    return str(company_settings.value(cid, name) or "")


def color():
    """Rangi kuu ya kampuni (#RRGGBB) au ya kawaida."""
    hexa = _value("_PRIMARY").strip()
    if len(hexa) == 7 and hexa.startswith("#"):
        try:
            return colors.HexColor(hexa)
        except Exception:
            pass
    return DEFAULT


def logo() -> ImageReader | None:
    """Picha ya logo ya kampuni ya sasa (cache kwa njia + muda wa kubadilishwa) au None."""
    relative = _value("_LOGO_PATH").strip()
    if not relative:
        return None
    from . import files

    try:
        path = files.absolute(relative)
        if not path.is_file():
            return None
        key = (str(path), path.stat().st_mtime)
        with _lock:
            hit = _images.get(key)
        if hit is not None:
            return hit
        image = ImageReader(str(path))
        image.getSize()  # inathibitisha picha inasomeka
    except Exception:
        logger.warning("Logo ya kampuni haisomeki: %s", relative)
        return None
    with _lock:
        if len(_images) > 200:
            _images.clear()
        _images[key] = image
    return image


def draw_logo(c, x: float, y: float, max_w: float, max_h: float) -> float:
    """Inachora logo (pembe ya chini-kushoto x,y) ndani ya max_w x max_h; inarudisha upana uliotumika (0 bila logo)."""
    image = logo()
    if image is None:
        return 0.0
    try:
        iw, ih = image.getSize()
        if not iw or not ih:
            return 0.0
        scale = min(max_w / iw, max_h / ih)
        w, h = iw * scale, ih * scale
        c.drawImage(image, x, y + (max_h - h) / 2, width=w, height=h, mask="auto", preserveAspectRatio=True)
        return w
    except Exception:
        logger.warning("Logo haikuchorwa kwenye PDF")
        return 0.0
