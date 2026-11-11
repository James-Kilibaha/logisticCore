"""
Majukumu ya wasimamizi wa mfumo (super admin):

  OWNER   - kila kitu (wasimamizi, kufuta kampuni, backup, server, export ya data)
  FINANCE - malipo, subscription, mipango, punguzo (coupon), nafasi za ziada, kusimamisha kwa kutolipa
  SUPPORT - kusajili/kuidhinisha kampuni, kuingia kama kampuni (kuangalia), nywila za watumiaji, msaada (tickets)
  VIEWER  - kusoma tu

Inatekelezwa na PlatformAuditMiddleware (kabla ya ombi kufika kwenye endpoint) kwa kila ombi la /api/platform.
"""
import re

ROLES = ("OWNER", "FINANCE", "SUPPORT", "VIEWER")

# kitendo (tazama audit_log.service._ACTIONS) -> majukumu yanayoruhusiwa (OWNER anaruhusiwa kila kitu)
ACTION_ROLES: dict[str, set[str]] = {
    "PAYMENT_RECORD": {"FINANCE"}, "PAYMENT_CONFIRM": {"FINANCE"}, "PAYMENT_REJECT": {"FINANCE"},
    "SUBSCRIPTION_EXTEND": {"FINANCE", "SUPPORT"}, "SUBSCRIPTION_PLAN": {"FINANCE"},
    "SUBSCRIPTION_CANCEL": {"FINANCE"}, "REMINDERS": {"FINANCE"},
    "PLAN_CREATE": {"FINANCE"}, "PLAN_UPDATE": {"FINANCE"}, "PLAN_DELETE": {"FINANCE"},
    "COUPON_CREATE": {"FINANCE"}, "COUPON_UPDATE": {"FINANCE"}, "COUPON_DELETE": {"FINANCE"},
    "COMPANY_LIMITS": {"FINANCE"}, "COMPANY_STATUS": {"FINANCE"},
    "COMPANY_CREATE": {"SUPPORT"}, "COMPANY_UPDATE": {"SUPPORT"}, "COMPANY_APPROVE": {"SUPPORT"},
    "COMPANY_REJECT": {"SUPPORT"}, "COMPANY_LOGO": {"SUPPORT"}, "TENANT_PASSWORD": {"SUPPORT"},
    "VIEW_AS": {"SUPPORT", "FINANCE"}, "TICKET_REPLY": {"SUPPORT"}, "TICKET_STATUS": {"SUPPORT"},
    "TENANT_LOGOUT": {"SUPPORT"},
    "PASSWORD": {"FINANCE", "SUPPORT", "VIEWER"},  # nywila yake mwenyewe
}
# Kusoma (GET) - kila jukumu, isipokuwa hizi (OWNER tu)
_OWNER_ONLY_GET = re.compile(r"^/(admins|server(/.*)?|companies/[^/]+/export)$")


def allowed(role: str | None, method: str, sub: str, action: str) -> bool:
    role = (role or "OWNER").upper()
    if role == "OWNER":
        return True
    if method in ("GET", "HEAD", "OPTIONS"):
        return not _OWNER_ONLY_GET.match(sub)
    return role in ACTION_ROLES.get(action, set())


def check(role: str | None) -> str:
    from ...core.exceptions import BadRequest

    value = (role or "OWNER").strip().upper()
    if value not in ROLES:
        raise BadRequest(f"Jukumu: {', '.join(ROLES)}")
    return value
