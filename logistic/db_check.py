"""
Ukaguzi wa muundo wa database dhidi ya models (bila kubadilisha chochote):

    python -m logistic.db_check

Mfumo unaongeza tables, columns na indexes mpya wenyewe (init_db + sync_schema), lakini HAUWEZI:
  - kubadilisha aina ya column (mf. String -> Integer),
  - kubadilisha NOT NULL ya column iliyopo,
  - kufuta columns zilizoondolewa kwenye models.
Ukaguzi huu unaonyesha tofauti hizo ili zirekebishwe kwa mkono (ALTER TABLE) au kwa migration,
kabla hazijaleta makosa wakati wa kuendesha. Pia unaendeshwa backend ikianza (onyo kwenye log).
"""
import logging
import sys

from sqlalchemy import inspect

logger = logging.getLogger(__name__)

# Familia za aina zinazolingana (jina la aina ya PostgreSQL -> familia)
_FAMILY = {
    "VARCHAR": "text", "TEXT": "text", "STRING": "text", "CHAR": "text",
    "INTEGER": "int", "BIGINT": "int", "SMALLINT": "int",
    "FLOAT": "float", "DOUBLE_PRECISION": "float", "DOUBLE PRECISION": "float", "REAL": "float", "NUMERIC": "float",
    "BOOLEAN": "bool", "UUID": "uuid", "DATE": "date", "TIMESTAMP": "datetime", "DATETIME": "datetime",
    "JSON": "json", "JSONB": "json",
}


def _family(type_) -> str:
    name = type(type_).__name__.upper()
    if name in _FAMILY:
        return _FAMILY[name]
    try:
        compiled = str(type_).upper().split("(")[0].strip()
    except Exception:
        compiled = name
    return _FAMILY.get(compiled, compiled.lower())


def check(engine=None) -> list[dict]:
    from . import models  # noqa: F401  (tables zote zisajiliwe)
    from .db import Base

    if engine is None:
        from .db import engine as default_engine

        engine = default_engine
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    problems: list[dict] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            problems.append({"table": table.name, "column": None, "kind": "MISSING_TABLE",
                             "detail": "table haipo (itaundwa backend ikianza)"})
            continue
        db_cols = {c["name"]: c for c in insp.get_columns(table.name)}
        for col in table.columns:
            info = db_cols.get(col.name)
            if info is None:
                problems.append({"table": table.name, "column": col.name, "kind": "MISSING_COLUMN",
                                 "detail": "column haipo (itaongezwa backend ikianza)"})
                continue
            want, have = _family(col.type), _family(info["type"])
            if want != have:
                problems.append({"table": table.name, "column": col.name, "kind": "TYPE",
                                 "detail": f"model: {col.type} · database: {info['type']}"})
            if not col.nullable and info.get("nullable") and not col.primary_key:
                problems.append({"table": table.name, "column": col.name, "kind": "NULLABLE",
                                 "detail": "model inasema NOT NULL lakini database inaruhusu NULL"})
            if col.nullable and not info.get("nullable") and not col.primary_key:
                problems.append({"table": table.name, "column": col.name, "kind": "NOT_NULL",
                                 "detail": "database ina NOT NULL lakini model inaruhusu tupu - inaweza kukataa data"})
        for name in db_cols:
            if name not in table.columns:
                problems.append({"table": table.name, "column": name, "kind": "EXTRA_COLUMN",
                                 "detail": "column ipo kwenye database lakini si kwenye model"})
    return problems


def log_problems(engine=None) -> int:
    """Backend ikianza: maonyo tu (haizuii kuanza)."""
    try:
        found = [p for p in check(engine) if p["kind"] in ("TYPE", "NOT_NULL", "NULLABLE")]
    except Exception:
        logger.exception("Ukaguzi wa muundo wa database umeshindwa")
        return 0
    for p in found:
        logger.warning("DB schema %s.%s [%s]: %s", p["table"], p["column"], p["kind"], p["detail"])
    return len(found)


def main() -> int:
    problems = check()
    serious = [p for p in problems if p["kind"] in ("TYPE", "NOT_NULL", "NULLABLE", "MISSING_TABLE", "MISSING_COLUMN")]
    if not problems:
        print("Muundo wa database unalingana na models.")
        return 0
    for p in problems:
        where = f"{p['table']}.{p['column']}" if p["column"] else p["table"]
        print(f"[{p['kind']:15}] {where:50} {p['detail']}")
    print(f"\nTofauti {len(problems)} ({len(serious)} za kurekebisha; EXTRA_COLUMN ni onyo tu).")
    return 1 if serious else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
