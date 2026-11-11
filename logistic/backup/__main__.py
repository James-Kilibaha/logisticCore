"""
    python -m logistic.backup create              # backup sasa hivi
    python -m logistic.backup list                # orodha
    python -m logistic.backup restore <faili.zip> # kurudisha (inafuta data ya sasa!)
"""
import sys

from ..db import create_database_if_not_exists
from . import service


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("create", "list", "restore"):
        print(__doc__)
        return 1
    if argv[0] == "create":
        print(service.create_backup(reason="cli"))
    elif argv[0] == "list":
        for item in service.list_backups():
            print(f"{item['name']}  {item['size'] / 1_048_576:.1f} MB  {item['created_at']}")
    else:
        if len(argv) < 2:
            print("Taja faili la backup")
            return 1
        answer = input("Data yote ya sasa itabadilishwa na ya backup. Andika NDIYO kuendelea: ")
        if answer.strip().upper() != "NDIYO":
            return 1
        create_database_if_not_exists()
        service.restore(argv[1])
        print("Imerudishwa. Washa server upya.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
