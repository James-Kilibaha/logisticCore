import random
import re
import string
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import config


def local_tz() -> ZoneInfo:
    return ZoneInfo(config.TIMEZONE)


def local_now() -> datetime:
    """Muda wa sasa kwa saa za ofisi (bila tzinfo)."""
    return datetime.now(local_tz()).replace(tzinfo=None)


def local_midnight_utc(day: date) -> datetime:
    """Saa 6 usiku (00:00) ya siku hiyo kwa saa za ofisi, ikiwa kama UTC bila tzinfo (kama database)."""
    return datetime.combine(day, time.min, tzinfo=local_tz()).astimezone(timezone.utc).replace(tzinfo=None)


def to_local(value: datetime | None) -> datetime | None:
    """UTC (bila tzinfo) -> saa za ofisi."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).astimezone(local_tz()).replace(tzinfo=None)


def clean_text(txt: str | None) -> str:
    """Inaondoa nafasi za ziada na alama; inarudisha maandishi safi (Title Case)."""
    if not txt:
        return ""
    txt = re.sub(r"\s\s+", " ", txt.strip())
    txt = re.sub(r"[^a-zA-Z0-9\s]", "", txt)
    return txt.title()


def clean_phone(phone: str | None) -> str:
    """Namba ya simu: tarakimu na herufi tu, bila nafasi."""
    return re.sub(r"[^a-zA-Z0-9]", "", phone or "")


def title(txt: str | None) -> str | None:
    return re.sub(r"\s\s+", " ", txt.strip()).title() if txt else txt


def money(value: float | None) -> str:
    return "{:,.2f}".format(value or 0)


def whole(value: float | None) -> str:
    return "{:,.0f}".format(value or 0)


def parse_date(value: str | None) -> date | None:
    """Inakubali '2026-10-13' au '2026-10-13T08:00:00...'."""
    if not value:
        return None
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def day_range(start: str | None, end: str | None) -> tuple[datetime | None, datetime | None]:
    """[start 00:00, end+1 00:00) - ili siku ya mwisho ihesabiwe yote."""
    s, e = parse_date(start), parse_date(end)
    start_dt = local_midnight_utc(s) if s else None
    end_dt = local_midnight_utc(e + timedelta(days=1)) if e else None
    return start_dt, end_dt


def stamp(status: str) -> str:
    """Kipande kimoja cha `history`: mfano 'SHIPPING_2026-10-13T12:00:00'."""
    return f"{status}_{datetime.now():%Y-%m-%dT%H:%M:%S}"


def random_box_key() -> str:
    """Kitambulisho cha box: mfano 'aB-3x-Q9'."""
    chars = string.ascii_letters + string.digits
    raw = "".join(random.choice(chars) for _ in range(6))
    return "-".join(raw[i:i + 2] for i in range(0, 6, 2))


def split_ids(value: str | None) -> list[str]:
    return [v for v in (value or "").split(",") if v]


def join_ids(values: list[str]) -> str:
    return ",".join(values)


def product_cbm(product) -> float:
    """Ujazo (m³) wa bidhaa: vipimo vya katoni moja (cm) x idadi ya katoni."""
    l, w, h = (getattr(product, k, 0) or 0 for k in ("length", "width", "height"))
    if l <= 0 or w <= 0 or h <= 0:
        return 0.0
    return l * w * h / 1_000_000 * max(getattr(product, "quantities", 1) or 1, 1)
