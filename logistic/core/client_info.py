"""
Kifaa na aina ya programu iliyotuma ombi (kwa kumbukumbu za vitendo / audit).

App yetu inatuma:  X-Client: android | ios | web | windows | macos | linux
                   X-Device: mf. "Samsung SM-A515F | Android 13" (ASCII tu)
Browser: kifaa kinasomwa kutoka User-Agent (mf. "Chrome 130 · Windows").
"""
import re
from contextvars import ContextVar

_current: ContextVar[dict | None] = ContextVar("client_info", default=None)

APP_PLATFORMS = {"android", "ios", "windows", "macos", "linux"}


def _clean(value: str | None, limit: int = 120) -> str:
    return re.sub(r"[\x00-\x1f]", "", value or "").strip()[:limit]


def _os(ua: str) -> str:
    if m := re.search(r"Android ([\d.]+)", ua):
        model = re.search(r"Android [\d.]+; (?:[a-z]{2}-[a-z]{2}; )?([^;)]+?)(?: Build|\))", ua)
        name = model.group(1).strip() if model and model.group(1).strip() not in ("K", "wv") else ""
        return f"{name} · Android {m.group(1)}".strip(" ·") if name else f"Android {m.group(1)}"
    if m := re.search(r"(iPhone|iPad).*?OS ([\d_]+)", ua):
        return f"{m.group(1)} · iOS {m.group(2).replace('_', '.')}"
    if "Windows NT 10" in ua:
        return "Windows 10/11"
    if m := re.search(r"Windows NT ([\d.]+)", ua):
        return f"Windows NT {m.group(1)}"
    if m := re.search(r"Mac OS X ([\d_]+)", ua):
        return f"macOS {m.group(1).replace('_', '.')}"
    if "CrOS" in ua:
        return "ChromeOS"
    if "Linux" in ua:
        return "Linux"
    return ""


def _browser(ua: str) -> str:
    for name, pattern in (("Edge", r"Edg(?:A|iOS)?/(\d+)"), ("Opera", r"OPR/(\d+)"),
                          ("Samsung Internet", r"SamsungBrowser/(\d+)"), ("Firefox", r"(?:Firefox|FxiOS)/(\d+)"),
                          ("Chrome", r"(?:Chrome|CriOS)/(\d+)"), ("Safari", r"Version/(\d+).*Safari")):
        if m := re.search(pattern, ua):
            return f"{name} {m.group(1)}"
    return ""


def describe(headers: dict) -> dict:
    """{client: APP/WEB/API, platform, device} kutoka kwenye headers (majina kwa herufi ndogo)."""
    ua = headers.get("user-agent", "") or ""
    platform = _clean(headers.get("x-client"), 20).lower()
    # headers ni ASCII tu: app inatenganisha kwa " | " -> " · "
    device = _clean(headers.get("x-device")).replace(" | ", " · ")
    if platform in APP_PLATFORMS:
        return {"client": "APP", "platform": platform, "device": device or platform.title()}
    if platform == "web" or "Mozilla/" in ua:
        parts = [p for p in (_browser(ua), _os(ua)) if p]
        return {"client": "WEB", "platform": "web", "device": " · ".join(parts) or device or "Browser"}
    if "Dart/" in ua:  # app ya zamani (kabla ya X-Client)
        return {"client": "APP", "platform": "", "device": "App (toleo la zamani)"}
    return {"client": "API", "platform": "", "device": _clean(ua, 80) or "-"}


def set_current(headers: dict):
    return _current.set(describe(headers))


def reset(token) -> None:
    _current.reset(token)


def current() -> dict:
    return _current.get() or {}
