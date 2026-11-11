"""
Inbox ya WhatsApp: majibu na ujumbe unaoingia kutoka kwa wateja.

- Webhook ya kampuni (saas/whatsapp) inaleta `messages` -> zinahifadhiwa hapa + taarifa kwa wenye ruhusa ya WhatsApp.
- Kujibu: ndani ya saa 24 tangu mteja alipoandika -> maandishi ya kawaida; nje ya hapo -> kupitia template
  (WHATSAPP_TEMPLATE) kama ipo, vinginevyo Meta inakataa.
- Mazungumzo yanaonyesha pia ujumbe uliotumwa na mfumo kwa namba hiyo (ankara, risiti ...) kutoka `sms`.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import config
from ..core import whatsapp
from ..core.base_model import utc_now
from ..core.exceptions import AppError, BadRequest, NotFound
from ..core.phone import normalize, try_normalize
from .model import WhatsappMessage

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=24)
MEDIA = ("image", "document", "audio", "video", "sticker")


# ------------------------------------------------------------------ kupokea (webhook)

def _parse(m: dict) -> dict:
    kind = m.get("type") or "unknown"
    out = {"kind": kind, "text": None, "mediaId": None, "mimeType": None, "fileName": None}
    if kind == "text":
        out["text"] = (m.get("text") or {}).get("body")
    elif kind in MEDIA:
        part = m.get(kind) or {}
        out.update(mediaId=part.get("id"), mimeType=part.get("mime_type"), fileName=part.get("filename"),
                   text=part.get("caption"))
    elif kind == "location":
        loc = m.get("location") or {}
        label = " - ".join(x for x in (loc.get("name"), loc.get("address")) if x)
        out["text"] = f"{loc.get('latitude')},{loc.get('longitude')}" + (f" ({label})" if label else "")
    elif kind == "button":
        out["text"] = (m.get("button") or {}).get("text")
    elif kind == "interactive":
        inter = m.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        out["text"] = reply.get("title")
    elif kind == "reaction":
        out["text"] = (m.get("reaction") or {}).get("emoji")
    elif kind == "contacts":
        names = [((c.get("name") or {}).get("formatted_name") or "") for c in m.get("contacts") or []]
        out["text"] = ", ".join(n for n in names if n)
    return out


def _when(ts) -> datetime:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return utc_now()


def receive(db: Session, payload: dict) -> int:
    """Ujumbe mpya kutoka webhook ya Meta (kampuni tayari imechaguliwa - tenant). Inarudisha idadi iliyohifadhiwa."""
    from ..notification.service import notify

    saved = 0
    for entry in (payload or {}).get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
            for m in value.get("messages") or []:
                wamid = m.get("id")
                phone = try_normalize("+" + str(m.get("from") or "").lstrip("+"))
                if not phone:
                    continue
                if wamid and db.query(WhatsappMessage.id).filter(WhatsappMessage.wamid == wamid).first():
                    continue  # Meta inaweza kutuma ujumbe ule ule zaidi ya mara moja
                data = _parse(m)
                name = names.get(m.get("from"))
                db.add(WhatsappMessage(phone=phone, profileName=name, direction="IN", wamid=wamid,
                                       status="RECEIVED", sentAt=_when(m.get("timestamp")), **data))
                db.flush()
                saved += 1
                preview = data["text"] or f"[{data['kind']}]"
                notify(db, "WHATSAPP", "select", kind="WHATSAPP_IN", title=f"WhatsApp: {name or phone}",
                       body=preview[:300], link=f"wa:{phone}", dedupe_hours=0.25)
            for st in value.get("statuses") or []:  # hali ya majibu yaliyotumwa kutoka inbox
                if not st.get("id"):
                    continue
                row = db.query(WhatsappMessage).filter(WhatsappMessage.wamid == st["id"],
                                                       WhatsappMessage.direction == "OUT").first()
                if row is not None and st.get("status"):
                    row.status = str(st["status"]).upper()
                    errors = st.get("errors") or []
                    if errors:
                        row.error = (errors[0].get("title") or errors[0].get("message") or "")[:300]
    db.commit()
    return saved


# ------------------------------------------------------------------ kusoma

def _customers(db: Session, phones: set[str]) -> dict[str, str]:
    from ..customer.model import Customer

    if not phones:
        return {}
    rows = db.query(Customer.phoneNumber, Customer.name).filter(Customer.phoneNumber.in_(phones)).all()
    return {p: n for p, n in rows}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def _window_until(last_in: datetime | None) -> datetime | None:
    return last_in + WINDOW if last_in else None


def conversations(db: Session, q: str | None = None, limit: int = 200) -> list[dict]:
    rows = (db.query(WhatsappMessage).order_by(WhatsappMessage.created_at.desc()).limit(5000).all())
    convs: dict[str, dict] = {}
    for r in rows:  # mpya kwanza
        c = convs.get(r.phone)
        if c is None:
            c = convs[r.phone] = {"phone": r.phone, "name": None, "lastText": r.text or f"[{r.kind}]",
                                  "lastKind": r.kind, "lastDirection": r.direction, "lastAt": r.created_at,
                                  "unread": 0, "lastInAt": None}
        if r.direction == "IN":
            c["name"] = c["name"] or r.profileName
            c["lastInAt"] = c["lastInAt"] or (r.sentAt or r.created_at)
            if r.readAt is None:
                c["unread"] += 1
    names = _customers(db, set(convs))
    now = utc_now()
    out = []
    for c in convs.values():
        customer = names.get(c["phone"])
        until = _window_until(c["lastInAt"])
        if q:
            needle = q.strip().lower()
            hay = " ".join(x for x in (c["phone"], c["name"], customer, c["lastText"]) if x).lower()
            if needle not in hay and needle.lstrip("0") not in c["phone"]:
                continue
        out.append({"phone": c["phone"], "name": c["name"], "customerName": customer, "lastText": c["lastText"][:200],
                    "lastKind": c["lastKind"], "lastDirection": c["lastDirection"], "lastAt": _iso(c["lastAt"]),
                    "unread": c["unread"], "windowOpen": bool(until and until > now),
                    "windowUntil": _iso(until)})
    return out[:limit]


def unread(db: Session) -> dict:
    n = (db.query(func.count(WhatsappMessage.id))
         .filter(WhatsappMessage.direction == "IN", WhatsappMessage.readAt.is_(None)).scalar())
    convs = (db.query(func.count(func.distinct(WhatsappMessage.phone)))
             .filter(WhatsappMessage.direction == "IN", WhatsappMessage.readAt.is_(None)).scalar())
    return {"messages": int(n or 0), "conversations": int(convs or 0)}


def _out(r: WhatsappMessage) -> dict:
    return {"id": str(r.id), "direction": r.direction, "kind": r.kind, "text": r.text, "status": r.status,
            "error": r.error, "hasMedia": bool(r.mediaId), "mimeType": r.mimeType, "fileName": r.fileName,
            "at": _iso(r.sentAt or r.created_at), "source": "INBOX", "byUser": str(r.user_id) if r.user_id else None}


def thread(db: Session, phone: str, mark_read: bool = True) -> dict:
    from ..sms.model import Sms
    from ..user.model import User

    phone = normalize(phone, required=True)
    rows = (db.query(WhatsappMessage).filter(WhatsappMessage.phone == phone)
            .order_by(WhatsappMessage.created_at.desc()).limit(300).all())
    system = (db.query(Sms).filter(Sms.msisdn == phone, Sms.channel == "WHATSAPP", Sms.isSMSSend.is_(True))
              .order_by(Sms.created_at.desc()).limit(100).all())
    users = {}
    ids = {r.user_id for r in rows if r.user_id}
    if ids:
        users = {u.id: f"{u.firstName} {u.lastName}".strip() or u.username
                 for u in db.query(User).filter(User.id.in_(ids)).all()}
    keyed = []  # (muda kamili, muda wa kuhifadhi, ujumbe) - mpangilio sahihi hata ndani ya sekunde moja
    for r in rows:
        item = _out(r)
        item["byName"] = users.get(r.user_id)
        keyed.append((r.sentAt or r.created_at, r.created_at, item))
    for s in system:
        keyed.append((s.sentAt or s.created_at, s.created_at, {
            "id": str(s.id), "direction": "OUT", "kind": "text", "text": s.text, "status": s.deliveryStatus or "SENT",
            "error": s.error, "hasMedia": False, "mimeType": None, "fileName": None,
            "at": _iso(s.sentAt or s.created_at), "source": "SYSTEM", "byName": None}))
    keyed.sort(key=lambda k: (k[0] or datetime.min, k[1] or datetime.min))
    messages = [k[2] for k in keyed]
    last_in = max((r.sentAt or r.created_at for r in rows if r.direction == "IN"), default=None)
    name = next((r.profileName for r in rows if r.direction == "IN" and r.profileName), None)
    if mark_read:
        changed = [r for r in rows if r.direction == "IN" and r.readAt is None]
        for r in changed:
            r.readAt = utc_now()
        if changed:
            db.commit()
    until = _window_until(last_in)
    return {"phone": phone, "name": name, "customerName": _customers(db, {phone}).get(phone),
            "windowOpen": bool(until and until > utc_now()), "windowUntil": _iso(until),
            "hasTemplate": bool(config.WHATSAPP_TEMPLATE), "messages": messages}


# ------------------------------------------------------------------ kujibu

def reply(db: Session, phone: str, text: str, user_id=None) -> dict:
    phone = normalize(phone, required=True)
    text = (text or "").strip()
    if not text:
        raise BadRequest("Andika ujumbe / message is empty")
    if not whatsapp.configured():
        raise BadRequest("WhatsApp haijaunganishwa - Mipangilio -> WhatsApp / WhatsApp is not connected")
    last_in = (db.query(func.max(func.coalesce(WhatsappMessage.sentAt, WhatsappMessage.created_at)))
               .filter(WhatsappMessage.phone == phone, WhatsappMessage.direction == "IN").scalar())
    window = bool(last_in and last_in + WINDOW > utc_now())
    if not window and not config.WHATSAPP_TEMPLATE:
        raise BadRequest("Saa 24 tangu mteja aandike zimepita: WhatsApp inaruhusu template tu. Weka template ya "
                         "ujumbe (Mipangilio -> WhatsApp) / the 24h window is closed and no template is set")
    try:
        wamid = whatsapp.send_free_text(phone, text) if window else whatsapp.send_template_text(phone, text)
    except AppError as error:
        raise BadRequest(str(error.detail))
    row = WhatsappMessage(phone=phone, direction="OUT", kind="text" if window else "template", text=text,
                          wamid=wamid or None, status="SENT", sentAt=utc_now(), user_id=user_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


def mark_read(db: Session, phone: str) -> dict:
    phone = normalize(phone, required=True)
    n = (db.query(WhatsappMessage)
         .filter(WhatsappMessage.phone == phone, WhatsappMessage.direction == "IN", WhatsappMessage.readAt.is_(None))
         .update({WhatsappMessage.readAt: utc_now()}, synchronize_session=False))
    db.commit()
    return {"updated": n}


def media(db: Session, message_id) -> tuple[bytes, str, str]:
    from ..core.dao import to_uuid

    pk = to_uuid(message_id)
    row = db.query(WhatsappMessage).filter(WhatsappMessage.id == pk).first() if pk else None
    if row is None or not row.mediaId:
        raise NotFound("Faili halipo / no media")
    content, mime = whatsapp.download_media(row.mediaId)
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf",
           "audio/ogg": "ogg", "audio/mpeg": "mp3", "video/mp4": "mp4"}.get((mime or "").split(";")[0], "bin")
    return content, mime, row.fileName or f"whatsapp_{str(row.id)[:8]}.{ext}"
