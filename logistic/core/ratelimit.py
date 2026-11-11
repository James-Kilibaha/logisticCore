"""
Kuzuia kubahatisha nywila: baada ya LOGIN_MAX_ATTEMPTS majaribio mabaya (kwa jina moja au IP moja)
ndani ya LOGIN_LOCK_MINUTES, kuingia kunafungwa kwa muda huo.
Inahifadhiwa kwenye kumbukumbu ya server (inafutika server ikiwashwa upya).
"""
import threading
import time
from collections import defaultdict, deque

from .. import config
from .exceptions import AppError

_lock = threading.Lock()
_failures: dict[str, deque] = defaultdict(deque)


class TooManyAttempts(AppError):
    status_code = 429


def _window() -> float:
    return config.LOGIN_LOCK_MINUTES * 60


def _scope() -> str:
    from . import tenant

    cid = tenant.company_id()
    return str(cid) if cid else "-"


def _keys(username: str, ip: str | None) -> list[str]:
    keys = [f"u:{_scope()}:{username.strip().lower()}"]
    if ip:
        keys.append(f"ip:{ip}")
    return keys


def _prune(q: deque, now: float) -> None:
    while q and now - q[0] > _window():
        q.popleft()


def check(username: str, ip: str | None) -> None:
    now = time.time()
    with _lock:
        for key in _keys(username, ip):
            q = _failures[key]
            _prune(q, now)
            # IP inaruhusiwa majaribio mara 4 zaidi (ofisi nzima inaweza kuwa nyuma ya IP moja)
            limit = config.LOGIN_MAX_ATTEMPTS * (4 if key.startswith("ip:") else 1)
            if len(q) >= limit:
                minutes = max(1, int((_window() - (now - q[0])) // 60) + 1)
                raise TooManyAttempts(f"Too many failed attempts. Try again in {minutes} minutes")


def failed(username: str, ip: str | None) -> None:
    now = time.time()
    with _lock:
        for key in _keys(username, ip):
            _failures[key].append(now)


def succeeded(username: str) -> None:
    with _lock:
        _failures.pop(f"u:{_scope()}:{username.strip().lower()}", None)


def reset() -> None:
    with _lock:
        _failures.clear()
        _hits.clear()


_hits: dict[str, deque] = defaultdict(deque)


def hit(key: str, limit: int, window_seconds: int) -> None:
    """Kizuizi cha jumla (mf. ukurasa wa umma): zaidi ya [limit] ndani ya sekunde [window_seconds] -> 429."""
    now = time.time()
    key = f"{_scope()}:{key}"
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            raise TooManyAttempts("Too many requests. Please wait a moment and try again")
        q.append(now)
