"""
Backup ya mfumo: database (pg_dump) + mafaili (picha, PDF) kwenye faili moja la .zip.

- Inaendeshwa yenyewe kila siku (scheduler) saa BACKUP_HOUR, na pia kwa mkono kutoka kwenye app.
- Backup BACKUP_KEEP za mwisho zinabaki; za zamani zinafutwa.
- Kama BACKUP_MIRROR_DIR imewekwa, nakala inanakiliwa huko pia (disk ya nje / folder la cloud).
- Kurudisha backup: `python -m logistic.backup restore <faili.zip>` (tazama README).
"""
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..core.exceptions import BadRequest, NotFound

logger = logging.getLogger(__name__)

PREFIX = "logistic_backup_"
_lock = threading.Lock()


def _dir() -> Path:
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return config.BACKUP_DIR


def _pg_env() -> dict:
    env = os.environ.copy()
    env["PGPASSWORD"] = config.DATABASE_PASSWORD or ""
    return env


def _pg_args() -> list[str]:
    return ["-h", config.DATABASE_HOST, "-p", str(config.DATABASE_PORT), "-U", config.DATABASE_USERNAME]


def _dump_database(target: Path) -> None:
    cmd = [config.PG_DUMP_PATH, *_pg_args(), "--no-owner", "--no-privileges", "--clean", "--if-exists",
           "-f", str(target), config.DATABASE_NAME]
    try:
        result = subprocess.run(cmd, env=_pg_env(), capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        raise BadRequest("pg_dump haipatikani kwenye server. Weka PG_DUMP_PATH kwenye .env")
    if result.returncode != 0:
        raise BadRequest(f"pg_dump failed: {result.stderr.strip()[:300]}")


def _file_roots() -> list[Path]:
    """Folda za mafaili ya mfumo (bila folder la backup lenyewe)."""
    root = config.FILES_DIR
    if not root.exists():
        return []
    backup = config.BACKUP_DIR.resolve()
    return [p for p in root.iterdir() if p.is_dir() and p.resolve() != backup and not p.name.startswith(".")]


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def create_backup(reason: str = "manual") -> dict:
    """Inatengeneza backup mpya na kurudisha maelezo yake."""
    if not _lock.acquire(blocking=False):
        raise BadRequest("Backup nyingine inaendelea, subiri imalize")
    try:
        name = f"{PREFIX}{datetime.now():%Y%m%d_%H%M%S}.zip"
        target = _dir() / name
        partial = target.with_suffix(".part")
        backup_dir = _dir()
        with tempfile.TemporaryDirectory() as tmp:
            sql = Path(tmp) / "database.sql"
            _dump_database(sql)
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                zf.write(sql, "database.sql")
                zf.writestr("info.txt", f"created={datetime.now().isoformat()}\nreason={reason}\n"
                                        f"database={config.DATABASE_NAME}\n")
                for root in _file_roots():
                    for path in root.rglob("*"):
                        if path.is_file() and not _is_inside(path, backup_dir):
                            zf.write(path, Path("files") / path.relative_to(config.FILES_DIR))
        partial.replace(target)
        _mirror(target)
        _prune()
        logger.info("Backup imekamilika: %s", target)
        return _info(target)
    finally:
        _lock.release()


def _mirror(path: Path) -> None:
    if not config.BACKUP_MIRROR_DIR:
        return
    try:
        mirror = Path(config.BACKUP_MIRROR_DIR)
        mirror.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, mirror / path.name)
        for old in sorted(mirror.glob(f"{PREFIX}*.zip"))[:-config.BACKUP_KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        logger.exception("Imeshindwa kunakili backup kwenda %s", config.BACKUP_MIRROR_DIR)


def _prune() -> None:
    keep = max(config.BACKUP_KEEP, 1)
    for old in sorted(_dir().glob(f"{PREFIX}*.zip"))[:-keep]:
        old.unlink(missing_ok=True)


def _info(path: Path) -> dict:
    stat = path.stat()
    return {"name": path.name, "size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")}


def list_backups() -> list[dict]:
    return [_info(p) for p in sorted(_dir().glob(f"{PREFIX}*.zip"), reverse=True)]


def path_of(name: str) -> Path:
    if not name.startswith(PREFIX) or not name.endswith(".zip") or "/" in name or "\\" in name:
        raise BadRequest("Invalid backup name")
    path = _dir() / name
    if not path.is_file():
        raise NotFound("Backup not found")
    return path


def delete_backup(name: str) -> bool:
    path_of(name).unlink()
    return True


def status() -> dict:
    items = list_backups()
    return {
        "enabled": config.BACKUP_ENABLED,
        "hour": config.BACKUP_HOUR,
        "keep": config.BACKUP_KEEP,
        "mirror": bool(config.BACKUP_MIRROR_DIR),
        "last": items[0] if items else None,
        "count": len(items),
    }


def scheduled_backup() -> None:
    create_backup(reason="scheduled")


def restore(zip_path: str) -> None:
    """Inarudisha database na mafaili kutoka kwenye backup (CLI tu - si kupitia API)."""
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp)
        sql = Path(tmp) / "database.sql"
        cmd = [config.PSQL_PATH, *_pg_args(), "-v", "ON_ERROR_STOP=1", "-q", "-f", str(sql), config.DATABASE_NAME]
        subprocess.run(cmd, env=_pg_env(), check=True)
        files_dir = Path(tmp) / "files"
        if files_dir.exists():
            shutil.copytree(files_dir, config.FILES_DIR, dirs_exist_ok=True)
