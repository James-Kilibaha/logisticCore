"""
Ripoti ya biashara yako (super admin): mapato kwa mwezi, kampuni mpya, zinazoondoka (churn),
zinazolipa, na kampuni zilizo hatarini kuondoka.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ... import config
from ...core.base_model import utc_now


def _month_start(d: datetime) -> datetime:
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(d: datetime, n: int) -> datetime:
    y, m = divmod(d.month - 1 + n, 12)
    return d.replace(year=d.year + y, month=m + 1, day=1)


def revenue(db: Session, months: int = 12) -> dict:
    from ..company.model import Company
    from ..subscription.model import Subscription, SubscriptionPayment

    months = max(1, min(months, 36))
    now = utc_now()
    first = _add_months(_month_start(now), -(months - 1))
    keys = [_add_months(first, i) for i in range(months)]
    label = {k: f"{k:%Y-%m}" for k in keys}
    grace = timedelta(days=max(config.SUBSCRIPTION_GRACE_DAYS, 0))

    rows = {k: {"month": label[k], "revenue": defaultdict(float), "payments": 0, "newCompanies": 0,
                "churned": 0, "paying": 0} for k in keys}

    pays = (db.query(SubscriptionPayment)
            .filter(SubscriptionPayment.status == "CONFIRMED",
                    func.coalesce(SubscriptionPayment.reviewedAt, SubscriptionPayment.created_at) >= first).all())
    by_company: dict = defaultdict(float)
    for p in pays:
        when = p.reviewedAt or p.created_at
        k = _month_start(when)
        if k in rows:
            rows[k]["revenue"][(p.currency or "TZS").upper()] += float(p.amount or 0)
            rows[k]["payments"] += 1
        if (p.currency or "TZS").upper() == "TZS":
            by_company[p.company_id] += float(p.amount or 0)

    companies = db.query(Company).filter(Company.status.in_(["ACTIVE", "SUSPENDED"])).all()
    for c in companies:
        if c.created_at and _month_start(c.created_at) in rows:
            rows[_month_start(c.created_at)]["newCompanies"] += 1

    subs = db.query(Subscription).filter(Subscription.status != "CANCELLED").all()
    per_company: dict = defaultdict(list)
    for s in subs:
        per_company[s.company_id].append(s)
    for cid, items in per_company.items():
        last_end = max(s.endsAt for s in items)
        # imeondoka: kipindi cha mwisho kimeisha (pamoja na siku za neema) na hakuna kipya
        if last_end + grace < now and _month_start(last_end) in rows:
            rows[_month_start(last_end)]["churned"] += 1
        for k in keys:
            end_of_month = _add_months(k, 1) - timedelta(seconds=1)
            check = min(end_of_month, now)
            if any(s.status == "ACTIVE" and s.startsAt <= check <= s.endsAt for s in items):
                rows[k]["paying"] += 1

    out_rows = []
    for k in keys:
        r = rows[k]
        out_rows.append({**r, "revenue": dict(r["revenue"]), "revenueTzs": round(r["revenue"].get("TZS", 0.0), 2)})

    names = {c.id: (c.name, c.slug) for c in companies}
    top = sorted(by_company.items(), key=lambda x: -x[1])[:10]
    totals = {
        "revenueTzs": round(sum(r["revenueTzs"] for r in out_rows), 2),
        "newCompanies": sum(r["newCompanies"] for r in out_rows),
        "churned": sum(r["churned"] for r in out_rows),
        "payingNow": out_rows[-1]["paying"] if out_rows else 0,
    }
    start_paying = out_rows[0]["paying"] if out_rows else 0
    totals["churnRate"] = round(100.0 * totals["churned"] / max(start_paying + totals["newCompanies"], 1), 1)
    return {
        "months": out_rows,
        "totals": totals,
        "top": [{"companyId": str(cid), "name": names.get(cid, ("-", ""))[0], "slug": names.get(cid, ("-", ""))[1],
                 "revenueTzs": round(v, 2)} for cid, v in top],
        "atRisk": at_risk(db),
    }


def at_risk(db: Session) -> list[dict]:
    """
    Kampuni zilizo hatarini kuondoka:
      - INACTIVE: hazijatengeneza ankara siku 14 (zina subscription hai)
      - EXPIRING: subscription inaisha ndani ya siku 7 na hakuna malipo yanayosubiri
      - TRIAL_ENDING: majaribio yanaisha ndani ya siku 3
      - EXPIRED: zimeisha (kusoma tu) ndani ya siku 30 zilizopita
    """
    from ..company.model import Company
    from ..subscription import service as subscriptions
    from ..subscription.model import SubscriptionPayment

    now = utc_now()
    since = now - timedelta(days=14)
    last_invoice = {r[0]: r[1] for r in db.execute(text(
        "SELECT company_id, MAX(created_at) FROM invoices GROUP BY company_id")).all()}
    recent = {r[0]: r[1] for r in db.execute(text(
        "SELECT company_id, COUNT(*) FROM invoices WHERE created_at >= :s GROUP BY company_id"), {"s": since}).all()}
    pending = {r[0] for r in db.query(SubscriptionPayment.company_id).filter(SubscriptionPayment.status == "PENDING")}
    out = []
    for c in db.query(Company).filter(Company.status == "ACTIVE").all():
        st = subscriptions.state(c.id)
        days = st.get("daysLeft")
        reasons = []
        if st["status"] in ("ACTIVE", "TRIAL", "GRACE") and not recent.get(c.id):
            reasons.append("INACTIVE")
        if st["status"] == "ACTIVE" and days is not None and days <= 7 and c.id not in pending:
            reasons.append("EXPIRING")
        if st["status"] == "TRIAL" and days is not None and days <= 3:
            reasons.append("TRIAL_ENDING")
        if st["status"] == "EXPIRED" and days is not None and days >= -30:
            reasons.append("EXPIRED")
        if reasons:
            li = last_invoice.get(c.id)
            out.append({"companyId": str(c.id), "name": c.name, "slug": c.slug, "status": st["status"],
                        "daysLeft": days, "reasons": reasons, "phone": c.ownerPhone or c.phone,
                        "lastInvoiceAt": li.isoformat(timespec="seconds") if li else None,
                        "invoices14d": int(recent.get(c.id, 0))})
    order = {"EXPIRING": 0, "TRIAL_ENDING": 1, "EXPIRED": 2, "INACTIVE": 3}
    out.sort(key=lambda r: min(order[x] for x in r["reasons"]))
    return out
