"""
Export ya data YOTE ya kampuni moja (ZIP):

    data/<table>.json   - kila safu ya kampuni hii (kwa programu / kuhamisha)
    data/<table>.csv    - ile ile kwa Excel
    files/...           - picha za mizigo, PDF, sahihi, risiti (folda ya kampuni)
    company.json        - taarifa za kampuni na mipangilio (bila siri)
    SOMA.txt            - maelezo

Nywila, siri za 2FA na token za SMS / WhatsApp / malipo HAZIMO.
Inatengenezwa kwenye faili la muda; inafutwa baada ya kupakuliwa.
"""
import csv
import io
import json
import os
import re
import tempfile
import zipfile
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ... import config
from ...core.base_model import utc_now

_SECRET_COLUMN = re.compile(r"^(password|otpHash|totp\w*|pin|secret\w*)$", re.I)
_SECRET_SETTING = re.compile(r"token|secret|password|api_?key|client_?secret|pin", re.I)


def _value(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, memoryview)):
        return None
    return v


def _settings(settings: dict | None) -> dict:
    return {k: ("***" if _SECRET_SETTING.search(k) else v) for k, v in (settings or {}).items()
            if not k.startswith("_")}


def tenant_tables() -> list:
    """Tables zenye company_id (data ya kampuni), kwa mpangilio wa utegemezi."""
    from ... import models  # noqa: F401  (tables zote zisajiliwe)
    from ...db import Base

    return [t for t in Base.metadata.sorted_tables if "company_id" in t.c]


def build(db, company) -> tuple[str, str, dict]:
    """(njia ya faili la muda, jina la kupakua, idadi kwa kila table)."""
    from ...core import files

    counts: dict[str, int] = {}
    fd, path = tempfile.mkstemp(prefix=f"export_{company.slug}_", suffix=".zip")
    os.close(fd)
    stamp = utc_now()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        conn = db.connection()
        for table in tenant_tables():
            rows = conn.execute(text(f'SELECT * FROM "{table.name}" WHERE company_id = :cid'),
                                {"cid": company.id}).mappings().all()
            counts[table.name] = len(rows)
            if not rows:
                continue
            columns = [c for c in rows[0].keys() if not _SECRET_COLUMN.match(c)]
            data = [{c: _value(r[c]) for c in columns} for r in rows]
            z.writestr(f"data/{table.name}.json", json.dumps(data, ensure_ascii=False, indent=1, default=str))
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(columns)
            for item in data:
                writer.writerow(["" if item[c] is None else
                                 (json.dumps(item[c], ensure_ascii=False) if isinstance(item[c], (dict, list))
                                  else item[c]) for c in columns])
            z.writestr(f"data/{table.name}.csv", "﻿" + buffer.getvalue())  # BOM: Excel inasoma UTF-8

        info = {c.name: _value(getattr(company, c.name)) for c in company.__table__.columns if c.name != "settings"}
        info["settings"] = _settings(company.settings)
        z.writestr("company.json", json.dumps(info, ensure_ascii=False, indent=1, default=str))

        root = files.absolute(str(company.id))
        n_files = 0
        if root.exists():
            for folder, _, names in os.walk(root):
                for name in names:
                    full = os.path.join(folder, name)
                    z.write(full, "files/" + os.path.relpath(full, root).replace(os.sep, "/"))
                    n_files += 1
        counts["_files"] = n_files

        lines = [
            f"Data ya {company.name} ({company.slug}) kutoka {config.PLATFORM_NAME}",
            f"Imetengenezwa: {stamp:%Y-%m-%d %H:%M} UTC",
            "",
            "data/*.json  - kila table (kwa programu au kuhamisha mfumo)",
            "data/*.csv   - kila table kwa Excel",
            "files/       - picha, PDF, sahihi na nyaraka za kampuni",
            "company.json - taarifa na mipangilio ya kampuni",
            "",
            "Nywila, siri za uthibitisho na token za SMS/WhatsApp/malipo hazimo kwa usalama.",
            "",
            "Idadi ya safu:",
            *[f"  {k:30} {v}" for k, v in sorted(counts.items()) if not k.startswith("_") and v],
            f"  {'faili':30} {n_files}",
        ]
        z.writestr("SOMA.txt", "\n".join(lines))
    return path, f"{company.slug}_data_{stamp:%Y%m%d_%H%M}.zip", counts
