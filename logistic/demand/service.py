"""
Madai ya gharama: kudai gharama za kazi iliyofanywa ziandikwe, kukumbusha na kuzuia kazi mpaka zijazwe.

Mtiririko:
1. Box linasafirishwa (BOX_CLOSED) au linafika (BOX_ARRIVED) -> `raise_for` inaunda dai (kama sheria imewashwa).
2. Saa ya kufunga kazi (remindAt) -> 🔔 kwa mhusika + mhasibu ("jaza kabla ya kufunga kazi").
3. Siku inayofuata (blockAt) -> kazi zinazuiwa (kuandika/kubadilisha chochote kunarudisha 423) mpaka:
   gharama zijazwe (dai linajifunga lenyewe), mhusika aseme "hakuna gharama", au mhasibu/msimamizi asamehe.
"""
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.base_model import utc_now
from ..core.dao import to_uuid
from ..core.enums import Action, Module
from ..core.exceptions import AppError, BadRequest, NotFound, PermissionDenied
from ..core.permission import allowed
from ..core.utils import local_midnight_utc, local_now, to_local
from .model import DONE, NONE, OPEN, TRIGGERS, WAIVED, CostDemand, DemandRule

COST_LABEL = {"FREIGHT": "Nauli", "CUSTOMS": "Ushuru", "CLEARING": "Clearing", "TRANSPORT": "Usafiri",
              "HANDLING": "Upakiaji", "OTHER": "Nyingine", "ANY": "Gharama yoyote"}
TRIGGER_LABEL = {"BOX_CLOSED": "Box limesafirishwa", "BOX_ARRIVED": "Box limefika stoo"}
DEFAULT_RULES = {
    "BOX_CLOSED": {"categories": "FREIGHT", "remindHour": 17, "graceDays": 0, "blockScope": "EVERYONE"},
    "BOX_ARRIVED": {"categories": "", "remindHour": 17, "graceDays": 0, "blockScope": "EVERYONE"},
}
SCOPES = ("EVERYONE", "RESPONSIBLE", "NONE")


# ------------------------------------------------------------------ sheria
def active() -> bool:
    """Madai ya gharama ni sehemu ya Uhasibu: kampuni ambayo mpango wake hauna ACCOUNTING haidaiwi wala kuzuiwa."""
    from ..saas.subscription.service import module_allowed

    return module_allowed(Module.ACCOUNTING.value)


def ensure_rules(db: Session) -> list[DemandRule]:
    have = {r.trigger: r for r in db.query(DemandRule).all()}
    added = False
    for trigger, values in DEFAULT_RULES.items():
        if trigger not in have:
            rule = DemandRule(trigger=trigger, enabled=True, responsible="DOER", **values)
            db.add(rule)
            have[trigger] = rule
            added = True
    if added:
        db.commit()
    return [have[t] for t in TRIGGERS]


def _split(value: str | None) -> list[str]:
    return [c for c in (value or "").split(",") if c]


def rule_row(db: Session, r: DemandRule) -> dict:
    from ..role.model import Role

    role = db.get(Role, r.role_id) if r.role_id else None
    return {"trigger": r.trigger, "label": TRIGGER_LABEL.get(r.trigger, r.trigger), "enabled": r.enabled,
            "categories": _split(r.categories), "responsible": r.responsible,
            "role_id": str(r.role_id) if r.role_id else None, "role": role.name if role else None,
            "remindHour": r.remindHour, "graceDays": r.graceDays, "blockScope": r.blockScope}


def rules(db: Session) -> list[dict]:
    return [rule_row(db, r) for r in ensure_rules(db)]


def save_rule(db: Session, trigger: str, data) -> dict:
    from ..core.audit import note
    from ..role.model import Role
    from ..shipment.model import COST_CATEGORIES

    ensure_rules(db)
    rule = db.query(DemandRule).filter(DemandRule.trigger == trigger.upper()).first()
    if rule is None:
        raise NotFound("Sheria haipo")
    cats = [c.strip().upper() for c in data.categories if c.strip()]
    bad = [c for c in cats if c not in COST_CATEGORIES]
    if bad:
        raise BadRequest(f"Aina ya gharama si sahihi: {', '.join(bad)}")
    if data.responsible not in ("DOER", "ROLE"):
        raise BadRequest("Mhusika si sahihi")
    if data.responsible == "ROLE" and (data.role_id is None or db.get(Role, data.role_id) is None):
        raise BadRequest("Chagua role ya mhusika")
    if data.blockScope not in SCOPES:
        raise BadRequest("Aina ya kuzuia si sahihi")
    if not 0 <= data.remindHour <= 23 or not 0 <= data.graceDays <= 30:
        raise BadRequest("Saa au siku si sahihi")
    rule.enabled, rule.categories = data.enabled, ",".join(dict.fromkeys(cats))
    rule.responsible = data.responsible
    rule.role_id = data.role_id if data.responsible == "ROLE" else None
    rule.remindHour, rule.graceDays, rule.blockScope = data.remindHour, data.graceDays, data.blockScope
    db.commit()
    note(f"Sheria ya madai ya gharama ({TRIGGER_LABEL.get(rule.trigger)}) imebadilishwa")
    return rule_row(db, rule)


# ------------------------------------------------------------------ msaada
def _user(db: Session, user_id):
    from ..user.model import User

    return db.get(User, to_uuid(user_id)) if user_id else None


def _name(user) -> str:
    if user is None:
        return "-"
    return f"{user.firstName or ''} {user.lastName or ''}".strip() or user.username


def missing(db: Session, d: CostDemand) -> list[str]:
    """Aina za gharama ambazo bado hazijaandikwa kwenye box (ANY = hakuna gharama yoyote bado)."""
    from ..expense.dao import approved_filter
    from ..expense.model import Expense
    from ..shipment.model import PackageCost

    present = {c for (c,) in db.query(PackageCost.category).filter(PackageCost.package_id == d.package_id).all()}
    cats = _split(d.categories)
    if not cats:
        has_expense = db.query(Expense.id).filter(Expense.package_id == d.package_id, approved_filter()).first()
        return [] if present or has_expense else ["ANY"]
    return [c for c in cats if c not in present]


def _close(d: CostDemand, status: str, user_id=None, note: str | None = None) -> None:
    d.status, d.closedAt, d.closedBy = status, utc_now(), to_uuid(user_id) if user_id else None
    if note:
        d.note = note


def refresh(db: Session, demands: list[CostDemand]) -> list[CostDemand]:
    """Madai ambayo gharama zake zimeshajazwa (kwa njia yoyote) yanajifunga yenyewe. Yanarudishwa yaliyobaki wazi."""
    still, changed = [], False
    for d in demands:
        if d.status == OPEN and not missing(db, d):
            _close(d, DONE)
            changed = True
        elif d.status == OPEN:
            still.append(d)
    if changed:
        db.commit()
    return still


def refresh_package(db: Session, package_id) -> None:
    if package_id:
        refresh(db, db.query(CostDemand).filter(CostDemand.package_id == to_uuid(package_id),
                                                CostDemand.status == OPEN).all())


def is_responsible(db: Session, d: CostDemand, user) -> bool:
    if user is None:
        return False
    if d.responsible == "ROLE":
        return d.role_id is not None and getattr(user, "role_id", None) == d.role_id
    return d.doer_id is not None and user.id == d.doer_id


def can_fill(db: Session, d: CostDemand, user) -> bool:
    return user is not None and (is_responsible(db, d, user)
                                 or allowed(db, user.id, Module.PROFIT, Action.UPDATE)
                                 or allowed(db, user.id, Module.ACCOUNTING, Action.UPDATE))


def _blocks(db: Session, d: CostDemand, user, now) -> bool:
    if d.status != OPEN or d.blockScope == "NONE" or d.blockAt > now:
        return False
    return d.blockScope == "EVERYONE" or is_responsible(db, d, user)


def responsible_name(db: Session, d: CostDemand) -> str:
    from ..role.model import Role

    if d.responsible == "ROLE":
        role = db.get(Role, d.role_id) if d.role_id else None
        return f"Role: {role.name}" if role else "Mhasibu"
    return _name(_user(db, d.doer_id))


def _recipients(db: Session, d: CostDemand, everyone: bool = False) -> set:
    """Wanaopata 🔔: mhusika (au wenye role), wenye ACCOUNTING/update; `everyone` = watumiaji wote hai."""
    from ..permission.model import Permission
    from ..user.model import User

    q = db.query(User.id).filter(User.isBlocked.is_(False), User.active == 1)
    if everyone:
        return {u for (u,) in q.all()}
    ids = set()
    if d.responsible == "ROLE" and d.role_id:
        ids |= {u for (u,) in q.filter(User.role_id == d.role_id).all()}
    elif d.doer_id:
        ids.add(d.doer_id)
    ids |= {u for (u,) in db.query(Permission.user_id).join(User, User.id == Permission.user_id)
            .filter(Permission.name == "ACCOUNTING", Permission.data_update.is_(True), User.isBlocked.is_(False),
                    User.active == 1).all()}
    return ids


def _describe(db: Session, d: CostDemand) -> tuple[str, str]:
    from ..package.model import Package

    box = db.get(Package, d.package_id)
    label = f"Box {box.boxId}" if box else "Box"
    what = ", ".join(COST_LABEL.get(c, c) for c in (missing(db, d) or _split(d.categories) or ["ANY"]))
    return label, what


def _notify(db: Session, d: CostDemand, title: str, body: str, everyone: bool = False) -> None:
    from ..notification.model import Notification

    for uid in _recipients(db, d, everyone):
        db.add(Notification(user_id=uid, kind="COST_DEMAND", title=title[:200], body=body[:500],
                            link="demands", isRead=False))


# ------------------------------------------------------------------ kuunda dai
def raise_for(db: Session, trigger: str, package, user_id) -> CostDemand | None:
    """Inaitwa kazi ikifanyika (box limesafirishwa / limefika). Haitupi kosa - kazi kuu isiharibike."""
    try:
        if not active():
            return None
        rule = next((r for r in ensure_rules(db) if r.trigger == trigger), None)
        if rule is None or not rule.enabled:
            return None
        if db.query(CostDemand.id).filter(CostDemand.package_id == package.id, CostDemand.trigger == trigger,
                                          CostDemand.status == OPEN).first():
            return None
        now_local = local_now()
        today = now_local.date()
        remind_at = local_midnight_utc(today) + timedelta(hours=rule.remindHour)
        block_at = local_midnight_utc(today + timedelta(days=1 + (rule.graceDays or 0)))
        d = CostDemand(trigger=trigger, package_id=package.id, categories=rule.categories or "",
                       doer_id=to_uuid(user_id) if user_id else None, responsible=rule.responsible,
                       role_id=rule.role_id, blockScope=rule.blockScope, remindAt=min(remind_at, block_at),
                       blockAt=block_at, status=OPEN, logsId=to_uuid(user_id) if user_id else package.logsId)
        if not missing(db, d):
            return None
        db.add(d)
        db.flush()
        label, what = _describe(db, d)
        _notify(db, d, f"Jaza gharama: {label} ({what})",
                f"{TRIGGER_LABEL.get(trigger)}. Jaza gharama ({what}) kabla ya kufunga kazi leo saa "
                f"{rule.remindHour:02d}:00. Asipojaza, kesho kazi zitazuiwa. Anayepaswa kujaza: "
                f"{responsible_name(db, d)}.")
        db.commit()
        return d
    except Exception:  # noqa: BLE001 - dai lisizuie kazi kuu
        db.rollback()
        import logging

        logging.getLogger("logistic.demand").exception("Imeshindwa kuunda dai la gharama")
        return None


# ------------------------------------------------------------------ kuzuia
def blocking(db: Session, user_id) -> list[CostDemand]:
    if not active():
        return []
    now = utc_now()
    rows = (db.query(CostDemand).filter(CostDemand.status == OPEN, CostDemand.blockAt <= now,
                                        CostDemand.blockScope != "NONE").all())
    if not rows:
        return []
    rows = refresh(db, rows)
    user = _user(db, user_id)
    return [d for d in rows if _blocks(db, d, user, now)]


def guard(db: Session, user_id) -> None:
    """Inaitwa na require() kwa kila kuandika/kubadilisha: 423 kama kuna dai lililopitwa na muda."""
    rows = blocking(db, user_id)
    if not rows:
        return
    d = rows[0]
    label, what = _describe(db, d)
    more = f" (na madai mengine {len(rows) - 1})" if len(rows) > 1 else ""
    raise AppError(f"Kazi zimezuiwa: gharama za {label} ({what}) hazijajazwa{more}. "
                   f"Anayepaswa kujaza: {responsible_name(db, d)}.", status_code=423)


# ------------------------------------------------------------------ kuonyesha
def _row(db: Session, d: CostDemand, user, now) -> dict:
    from ..package.model import Package

    box = db.get(Package, d.package_id)
    miss = missing(db, d) if d.status == OPEN else []
    return {"id": str(d.id), "trigger": d.trigger, "triggerLabel": TRIGGER_LABEL.get(d.trigger, d.trigger),
            "package_id": str(d.package_id), "boxId": box.boxId if box else None,
            "trackNumber": box.trackNumber if box else None,
            "categories": _split(d.categories), "missing": miss,
            "missingLabel": ", ".join(COST_LABEL.get(c, c) for c in miss),
            "responsible": responsible_name(db, d), "doer": _name(_user(db, d.doer_id)) if d.doer_id else None,
            "status": d.status, "note": d.note, "closedBy": _name(_user(db, d.closedBy)) if d.closedBy else None,
            "closedAt": d.closedAt.isoformat() if d.closedAt else None,
            "remindAt": d.remindAt.isoformat() if d.remindAt else None,
            "blockAt": d.blockAt.isoformat() if d.blockAt else None,
            "remindLocal": to_local(d.remindAt).strftime("%d/%m %H:%M") if d.remindAt else None,
            "blockLocal": to_local(d.blockAt).strftime("%d/%m %H:%M") if d.blockAt else None,
            "remind": d.status == OPEN and d.remindAt <= now, "blocking": _blocks(db, d, user, now),
            "isResponsible": is_responsible(db, d, user), "canFill": d.status == OPEN and can_fill(db, d, user),
            "canWaive": d.status == OPEN and user is not None
            and allowed(db, user.id, Module.ACCOUNTING, Action.UPDATE),
            "created_at": d.created_at.isoformat() if d.created_at else None}


def mine(db: Session, user_id) -> dict:
    """Madai wazi yanayomhusu mtumiaji: anayepaswa kujaza, yanayomzuia, au yote (mhasibu)."""
    if not active():
        return {"items": [], "blocked": False, "remind": False}
    now = utc_now()
    user = _user(db, user_id)
    rows = refresh(db, db.query(CostDemand).filter(CostDemand.status == OPEN)
                   .order_by(CostDemand.created_at).all())
    sees_all = user is not None and (allowed(db, user.id, Module.ACCOUNTING, Action.SELECT)
                                     or allowed(db, user.id, Module.PROFIT, Action.UPDATE))
    items = [_row(db, d, user, now) for d in rows
             if sees_all or is_responsible(db, d, user) or _blocks(db, d, user, now)]
    return {"items": items, "blocked": any(i["blocking"] for i in items),
            "remind": any(i["remind"] and (i["isResponsible"] or i["canFill"]) for i in items)}


def list_all(db: Session, user_id, status: str | None = None, limit: int = 300) -> list[dict]:
    q = db.query(CostDemand)
    if status:
        q = q.filter(CostDemand.status == status.upper())
    rows = q.order_by(CostDemand.created_at.desc()).limit(limit).all()
    refresh(db, [d for d in rows if d.status == OPEN])
    now, user = utc_now(), _user(db, user_id)
    return [_row(db, d, user, now) for d in rows]


# ------------------------------------------------------------------ kujaza / kufunga
def _get(db: Session, demand_id) -> CostDemand:
    d = db.get(CostDemand, to_uuid(demand_id))
    if d is None:
        raise NotFound("Dai halipo")
    return d


def fill(db: Session, demand_id, costs: list, user_id) -> dict:
    from ..core.audit import note
    from ..shipment import service as shipment

    d = _get(db, demand_id)
    user = _user(db, user_id)
    if d.status != OPEN:
        raise BadRequest("Dai hili limeshafungwa")
    if not can_fill(db, d, user):
        raise PermissionDenied(f"Gharama hizi zinajazwa na {responsible_name(db, d)} au mhasibu")
    if not costs:
        raise BadRequest("Weka angalau gharama moja")
    for c in costs:
        shipment.add_cost(db, d.package_id, c, user_id)
    refresh(db, [d])
    label, what = _describe(db, d)
    if d.status == OPEN:
        note(f"{label}: gharama zimeongezwa, bado zinadaiwa: {what}")
    return _row(db, d, user, utc_now())


def _shares(db: Session, demands: list[CostDemand], data) -> dict:
    """Kiasi cha kila box (kwa sarafu ya gharama) kulingana na `mode`."""
    from ..package.model import Package
    from ..shipment.service import box_kg

    mode = (data.mode or "EACH").upper()
    ids = [str(d.id) for d in demands]
    if mode == "MANUAL":
        out = {i: round(float(data.amounts.get(i) or 0), 2) for i in ids}
    else:
        if not data.amount or data.amount <= 0:
            raise BadRequest("Weka kiasi")
        if mode == "EACH":
            return {i: round(data.amount, 2) for i in ids}
        if mode == "WEIGHT":
            weights = {str(d.id): box_kg(db, db.get(Package, d.package_id)) for d in demands}
        elif mode == "EQUAL":
            weights = {i: 1.0 for i in ids}
        else:
            raise BadRequest("Njia ya kugawa si sahihi")
        total_w = sum(weights.values())
        if total_w <= 0:  # mabox hayana uzito -> sawa kwa sawa
            weights, total_w = {i: 1.0 for i in ids}, float(len(ids))
        out, left = {}, round(data.amount, 2)
        for n, i in enumerate(ids):
            share = left if n == len(ids) - 1 else round(data.amount * weights[i] / total_w, 2)
            out[i] = share
            left = round(left - share, 2)
    return out


def fill_many(db: Session, data, user_id) -> dict:
    """Gharama moja kwa mabox mengi: kila box kiasi chake, au jumla ikigawanywa (sawa / uzito / kwa mkono)."""
    from ..core.audit import note
    from ..package.model import Package
    from ..shipment import service as shipment
    from ..shipment.model import COST_CATEGORIES
    from ..shipment.schema import CostCreate

    user = _user(db, user_id)
    category = (data.category or "").strip().upper()
    if category not in COST_CATEGORIES:
        raise BadRequest("Aina ya gharama si sahihi")
    demands = []
    for i in dict.fromkeys(data.demandIds):
        d = _get(db, i)
        if d.status != OPEN:
            raise BadRequest("Dai mojawapo limeshafungwa - onyesha upya orodha")
        if not can_fill(db, d, user):
            label, _ = _describe(db, d)
            raise PermissionDenied(f"{label}: inajazwa na {responsible_name(db, d)} au mhasibu")
        demands.append(d)
    shares = _shares(db, demands, data)
    total = round(sum(shares.values()), 2)
    pay = (data.payStatus or "PAID").upper()
    if pay == "PARTIAL" and not (data.paidAmount and 0 < data.paidAmount < total):
        raise BadRequest("Kilicholipwa kiwe zaidi ya 0 na chini ya jumla ya gharama")
    boxes = {d.package_id: db.get(Package, d.package_id) for d in demands}
    plan = [{"demand_id": str(d.id), "package_id": str(d.package_id),
             "boxId": boxes[d.package_id].boxId if boxes[d.package_id] else None,
             "amount": shares[str(d.id)],
             "paid": shares[str(d.id)] if pay == "PAID" else 0.0 if pay == "CREDIT"
             else round((data.paidAmount or 0) * shares[str(d.id)] / total, 2) if total else 0.0}
            for d in demands]
    if data.preview:
        return {"total": total, "items": plan}
    if any(p["amount"] <= 0 for p in plan):
        raise BadRequest("Kila box liwe na kiasi zaidi ya 0")
    for p in plan:
        status = pay
        if pay == "PARTIAL" and not 0 < p["paid"] < p["amount"]:
            status = "PAID" if p["paid"] >= p["amount"] else "CREDIT"
        shipment.add_cost(db, p["package_id"], CostCreate(
            category=category, amount=p["amount"], currency=data.currency, note=data.note, payStatus=status,
            paidAmount=p["paid"] if status == "PARTIAL" else None, supplier=data.supplier,
            institute_id=data.institute_id), user_id, commit=False)
    db.commit()
    for d in demands:
        refresh_package(db, d.package_id)
    note(f"Gharama {category} imejazwa kwa mabox {len(plan)} (jumla {data.currency} {total:,.2f})")
    now = utc_now()
    return {"total": total, "items": plan, "demands": [_row(db, d, user, now) for d in demands]}


def no_cost(db: Session, demand_id, reason: str, user_id) -> dict:
    from ..core.audit import note

    d = _get(db, demand_id)
    user = _user(db, user_id)
    if d.status != OPEN:
        raise BadRequest("Dai hili limeshafungwa")
    if not can_fill(db, d, user):
        raise PermissionDenied(f"Hili linajibiwa na {responsible_name(db, d)} au mhasibu")
    _close(d, NONE, user_id, reason.strip())
    db.commit()
    label, _ = _describe(db, d)
    note(f"{label}: hakuna gharama ({reason.strip()})")
    return _row(db, d, user, utc_now())


def waive(db: Session, demand_id, reason: str, user_id) -> dict:
    from ..core.audit import note

    d = _get(db, demand_id)
    if d.status != OPEN:
        raise BadRequest("Dai hili limeshafungwa")
    _close(d, WAIVED, user_id, reason.strip())
    db.commit()
    label, _ = _describe(db, d)
    note(f"{label}: dai la gharama limesamehewa ({reason.strip()})")
    return _row(db, d, _user(db, user_id), utc_now())


# ------------------------------------------------------------------ ratiba (kila saa)
def remind(db: Session) -> int:
    """Kumbusho saa ya kufunga kazi, na taarifa siku ya kuzuia. Inarudisha idadi ya taarifa zilizotumwa."""
    if not active():
        return 0
    now = utc_now()
    rows = refresh(db, db.query(CostDemand).filter(CostDemand.status == OPEN, CostDemand.remindAt <= now).all())
    sent = 0
    for d in rows:
        label, what = _describe(db, d)
        who = responsible_name(db, d)
        if d.blockAt <= now and d.blockNotifiedAt is None:
            scope = "Kazi zote zimezuiwa" if d.blockScope == "EVERYONE" else \
                "Kazi za mhusika zimezuiwa" if d.blockScope == "RESPONSIBLE" else "Bado halijajazwa"
            _notify(db, d, f"⛔ {scope}: gharama za {label} ({what})",
                    f"Gharama za {label} ({what}) hazijajazwa tangu jana. Anayepaswa kujaza: {who}. "
                    "Zikijazwa, kazi zinaendelea.", everyone=d.blockScope == "EVERYONE")
            d.blockNotifiedAt = d.remindedAt = now
            sent += 1
        elif d.remindedAt is None:
            _notify(db, d, f"⏰ Muda wa kufunga kazi: jaza gharama za {label}",
                    f"Gharama ({what}) za {label} hazijajazwa. Anayepaswa kujaza: {who}. "
                    f"Zisipojazwa, kazi zitazuiwa kuanzia {to_local(d.blockAt):%d/%m %H:%M}.")
            d.remindedAt = now
            sent += 1
    db.commit()
    return sent


def scheduled() -> None:
    from ..db import session_scope

    with session_scope() as db:
        remind(db)
