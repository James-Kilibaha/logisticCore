"""
Kuunda au kubadilisha nywila ya super admin (platform admin) kutoka terminal:

    python -m logistic.saas.admin create  <username> <password> [jina kamili]
    python -m logistic.saas.admin password <username> <password_mpya>
    python -m logistic.saas.admin list
    python -m logistic.saas.admin reset-2fa <username>      (simu ya Authenticator imepotea)
"""
import sys

from ...core import tenant
from ...core.security import hash_password, password_problem
from ...db import SessionLocal, init_db
from .dao import PlatformAdminDao


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("create", "password", "list", "reset-2fa"):
        print(__doc__)
        return 1
    init_db()  # database na tables (kama bado hazipo)
    with tenant.system():
        db = SessionLocal()
        try:
            dao = PlatformAdminDao(db)
            if argv[0] == "list":
                for a in dao.ordered():
                    print(f"- {a.username:20} {a.fullName:30} {'hai' if a.active else 'amezuiwa'}"
                          f"{'  [2FA]' if a.totpEnabled else ''}")
                if dao.count() == 0:
                    print("Hakuna super admin bado. Tumia: python -m logistic.saas.admin create <username> <password>")
                return 0
            if argv[0] == "reset-2fa" and len(argv) >= 2:
                admin = dao.by_username(argv[1].strip())
                if admin is None:
                    print(f"Hakuna super admin '{argv[1]}'")
                    return 1
                admin.totpEnabled = False
                admin.totpSecret = None
                admin.totpRecovery = None
                admin.totpLastCounter = None
                admin.tokenVersion = int(admin.tokenVersion or 0) + 1
                db.commit()
                print(f"2FA ya '{admin.username}' imeondolewa. Aingie kwa nywila, kisha aiwashe upya.")
                return 0
            if len(argv) < 3:
                print(__doc__)
                return 1
            username, password = argv[1].strip(), argv[2]
            problem = password_problem(password)
            if problem:
                print(f"Nywila haikubaliki: {problem}")
                return 1
            admin = dao.by_username(username)
            if argv[0] == "create":
                if admin is not None:
                    print(f"'{username}' yupo tayari - tumia: python -m logistic.saas.admin password {username} <nywila>")
                    return 1
                name = " ".join(argv[3:]).strip() or "Super Admin"
                dao.create(username=username, password=hash_password(password), fullName=name, active=True)
                print(f"Super admin '{username}' ameundwa. Ingia kwenye  /#/super-admin")
                return 0
            if admin is None:
                print(f"Hakuna super admin '{username}'")
                return 1
            admin.password = hash_password(password)
            admin.active = True
            admin.tokenVersion = int(admin.tokenVersion or 0) + 1
            db.commit()
            print(f"Nywila ya '{username}' imebadilishwa.")
            return 0
        finally:
            db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
