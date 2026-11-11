"""
SMS: kuandaa (queue), kutafuta, kutuma kupitia gateway na maandishi ya ujumbe.
"""
import logging
from datetime import datetime, timedelta

import requests
from sqlalchemy import event
from sqlalchemy.orm import Session

from ..core import tenant
from .. import config
from ..core.enums import ESmsStatus
from ..core.exceptions import AppError, BadRequest, NotFound
from ..core.utils import product_cbm, whole
from ..settings.sms_set.dao import SmsSetDao
from . import schema
from .dao import SmsDao
from .model import Sms

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ messages
def _contacts() -> str:
    return f"Kwa mawasiliano Zaidi Piga namba Hizi : {config.COMPANY_PHONES}"


def track_link(code: str | None) -> str:
    """Kiungo cha kufuatilia mzigo (kama PUBLIC_TRACK_URL imewekwa)."""
    if not config.PUBLIC_TRACK_URL or not code:
        return ""
    sep = "&" if "?" in config.PUBLIC_TRACK_URL else "?"
    return f" Fuatilia: {config.PUBLIC_TRACK_URL}{sep}code={code}"


def _carrier(carrier: str | None) -> str:
    return "Meli" if (carrier or "").upper() == "SEA" else "Ndege"


# ------------------------------------------------------- bidhaa za ankara (mstari mmoja kwa kila bidhaa)
def _is_sea(product) -> bool:
    return (getattr(product, "carrierType", "") or "").upper() == "SEA"


def _tons(kg: float | None) -> str:
    return f"{(kg or 0) / 1000:,.2f}"


def _cbm(product) -> float:
    """CBM iliyotolewa moja kwa moja (mf. makadirio), au kutoka vipimo vya katoni."""
    direct = getattr(product, "cbm", None)
    if isinstance(direct, (int, float)) and direct > 0:
        return float(direct)
    return product_cbm(product)


def _measure(product) -> str:
    """Meli (container) = CBM na tani; ndege = kilo."""
    if _is_sea(product):
        cbm = _cbm(product)
        parts = [f"CBM {cbm:,.2f}"] if cbm > 0 else []
        if product.weight:
            parts.append(f"Tani {_tons(product.weight)}")
        return ", ".join(parts) or "CBM 0"
    return f"Kg {product.weight or 0:,.1f}"


def item_line(n: int, product, with_price: bool = True, with_code: bool = False) -> str:
    """'1. Viatu - Ctn 3, Kg 45.0 (Ndege) Tsh 450,000/= Code K7Q4M2'"""
    line = f"{n}. {product.description} - Ctn {whole(product.quantities)}, {_measure(product)} ({_carrier(product.carrierType)})"
    if with_price:
        line += f" Tsh {whole(product.unitPrice)}/="
    if with_code and getattr(product, "officeCode", None):
        line += f" Code {product.officeCode}"
    return line


def items_block(products, with_price: bool = True, with_code: bool = False) -> str:
    """Bidhaa zote za ankara, moja kwa mstari; zikizidi SMS_ITEMS_MAX zilizobaki zinajumlishwa."""
    products = list(products)
    limit = max(config.SMS_ITEMS_MAX, 1)
    lines = [item_line(i, p, with_price, with_code) for i, p in enumerate(products[:limit], 1)]
    rest = products[limit:]
    if rest:
        extra = f"...na bidhaa {len(rest)} zaidi (Ctn {whole(sum(p.quantities or 0 for p in rest))}"
        extra += f", Tsh {whole(sum(p.unitPrice or 0 for p in rest))}/=)" if with_price else ")"
        lines.append(extra)
    return "\n".join(lines)


def totals_line(products, with_price: bool = True) -> str:
    products = list(products)
    air = [p for p in products if not _is_sea(p)]
    sea = [p for p in products if _is_sea(p)]
    text = f"Jumla: Ctn {whole(sum(p.quantities or 0 for p in products))}"
    if air:
        text += f", Kg {sum(p.weight or 0 for p in air):,.1f}"
    if sea:
        cbm = sum(_cbm(p) for p in sea)
        if cbm > 0:
            text += f", CBM {cbm:,.2f}"
        kg = sum(p.weight or 0 for p in sea)
        if kg:
            text += f", Tani {_tons(kg)}"
    if with_price:
        text += f", Tsh {whole(sum(p.unitPrice or 0 for p in products))}/="
    return text


CODE_NOTE = "Onyesha Code ya kila mzigo unapouchukua ofisini."


def tracking_code(product) -> str | None:
    """Namba ya kufuatilia mzigo kwenye SMS: code ya ofisi (au track number kwa mizigo ya zamani)."""
    return getattr(product, "officeCode", None) or getattr(product, "trackNumber", None)


def received_message(product, name: str | None = None) -> str:
    hello = f"Habari {name}, " if name else ""
    code = getattr(product, "officeCode", None)
    ref = (f"Code ya ofisi: {code}" if code else f"Track No.{product.trackNumber or '-'}")
    return (f"{hello}Tumepokea leo mzigo wako wa {product.description} {config.COMPANY_ORIGIN} "
            f"({_carrier(product.carrierType)}) {ref} {_measure(product)} "
            f"Gharama yake {whole(product.unitPrice)}/="
            + (". Itumie kufuatilia mzigo na uionyeshe unapouchukua." if code else "")
            + f"{track_link(tracking_code(product))} {_contacts()}")


def _has_codes(products) -> bool:
    return any(getattr(p, "officeCode", None) for p in products)


def shipping_message(products, name: str | None = None, invoice_number: str | None = None, eta=None) -> str:
    """Ujumbe mmoja kwa invoice nzima, ukiorodhesha kila bidhaa iliyosafirishwa."""
    products = list(products)
    hello = f"Habari {name}," if name else "Habari,"
    carriers = {_carrier(p.carrierType) for p in products}
    ref = f" wa ankara #{invoice_number}" if invoice_number else ""
    # mizigo ya zamani (bila code ya ofisi) inaonyesha track number
    tracks = ", ".join(p.trackNumber for p in products if p.trackNumber and not getattr(p, "officeCode", None))
    return (f"{hello} mzigo wako{ref} umeondoka leo Tar {datetime.today():%d/%m} kwa {' na '.join(sorted(carriers))}:"
            f"\n{items_block(products, with_price=False, with_code=True)}"
            f"\n{totals_line(products, with_price=False)}"
            + (f"\nTrack No. {tracks}" if tracks else "")
            + (f"\nUnatarajiwa kufika Tanzania: {eta:%d/%m/%Y}" if eta else "")
            + (f"\n{CODE_NOTE}" if _has_codes(products) else "")
            + f"\nUkifika tutakutaarifu.{track_link(tracking_code(products[0]) if products else None)} Ahsante")


def store_message(d: schema.StoreDetails) -> str:
    ref = f" (ankara #{d.invoiceNumber})" if d.invoiceNumber else ""
    if d.items:  # bidhaa moja moja + jumla (meli: CBM/tani, ndege: kilo)
        arrived = (f"\nTunapenda kukujulisha kuwa mzigo wako{ref} kutoka {config.COMPANY_ORIGIN.upper()} "
                   f"umefika ofisini kwetu Tanzania:\n{d.items}" + (f"\n{d.totals}" if d.totals else ""))
    else:
        arrived = (f"\nTunapenda kukujulisha kuwa mzigo wako{ref} kutoka {config.COMPANY_ORIGIN.upper()} wenye katon "
                   f"{whole(d.quantity)}, Kilo {d.kg:,.1f} Umefika ofisini kwetu Tanzania.")
    return (f"Habari {d.name}{arrived}"
            f"\nTafadhali kamilisha malipo ya Tsh {whole(d.amount)}/= sawa na Dola {d.usd:,.2f}$"
            f"\nMizigo itakaa ofisini kwetu ndani ya siku {config.DAYS_TO_CHARGE} tu baada ya hapo mteja "
            f"atachajiwa gharama za kuhifadhi ambayo ni Dola {config.STORAGE_CHARGE_USD:,.2f}$ Kwa kila siku 1"
            f"\n{config.COMPANY_PAYMENT_INFO}"
            + (f"\n{CODE_NOTE}" if d.hasCodes else "")
            + f"\nTupigie kupitia\n{config.COMPANY_PHONES}")


# ---------------------------------------------------------- swichi za aina za SMS
KIND_LABELS = {
    "RECEIVED": "Mzigo umepokelewa", "SHIPPING": "Mzigo umesafirishwa", "STORE": "Mzigo umefika stoo",
    "REMAINDER": "Vikumbusho vya deni", "WHATSAPP": "Nakala za WhatsApp", "RECEIPT": "Risiti za malipo",
    "HANDOVER": "Mzigo umekabidhiwa", "STORAGE_WARN": "Onyo la siku za bure za stoo",
    "STORAGE_OVERDUE": "Kumbusho la mizigo iliyokaa stoo", "BROADCAST": "Ujumbe kwa wateja",
    "INVOICE_SMS": "SMS ya ankara", "QUOTATION": "Makadirio ya bei", "ETA": "Mabadiliko ya tarehe ya kufika",
    "OTP_LOGIN": "Code ya kuingia (2FA)", "OTP_RESET": "Code ya kusahau nywila", "ALERT": "Tahadhari za mfumo",
}


def kind_enabled(db: Session, kind: ESmsStatus) -> bool:
    return SmsSetDao(db).is_enabled(kind.name)


def ensure_enabled(db: Session, kind: ESmsStatus) -> None:
    """Kwa SMS zinazotumwa kwa mkono: aina iliyozimwa -> kosa linaloeleweka (si kimya)."""
    if not kind_enabled(db, kind):
        label = KIND_LABELS.get(kind.name, kind.name)
        raise BadRequest(f"SMS za \"{label}\" zimezimwa. Ziwashe kwenye Mipangilio → Aina za SMS "
                         f"/ this SMS type is turned off in Settings")


# --------------------------------------------------------------------- queue
_AUTO_KEY = "sms_auto_send"


def queue(db: Session, kind: ESmsStatus, *, text: str, msisdn: str, reference: str, invoice_id, logs_id,
          commit: bool = True, auto: bool | None = None) -> Sms | None:
    """
    Inahifadhi SMS (kama aina hii imewashwa kwenye Settings). Kama `SMS_AUTO_SEND` iko wazi,
    SMS inatumwa yenyewe mara tu transaction ikifanikiwa (commit) - bila kuchelewesha request.
    """
    from ..core.phone import try_normalize

    msisdn = try_normalize(msisdn)  # +255XXXXXXXXX; mteja asiye na namba (au namba mbovu) hatumiwi
    if not msisdn or not SmsSetDao(db).is_enabled(kind.name):
        return None
    dao = SmsDao(db)
    sms = dao.create(commit=False, text=text, msisdn=msisdn, source=config.SMS_SOURCE_NAME,
                     reference=reference, coding=config.SMS_CODING, smsFor=kind.name,
                     isReceived=False, isSMSSend=False, channel="SMS", invoice_id=invoice_id, logsId=logs_id)
    # Nakala ya WhatsApp (kama WhatsApp imewekwa kwenye .env na imewashwa kwenye Mipangilio -> SMS -> WHATSAPP)
    twin = None
    if config.WHATSAPP_ENABLED and SmsSetDao(db).is_enabled(ESmsStatus.WHATSAPP.name):
        twin = dao.create(commit=False, text=text, msisdn=msisdn, source="WhatsApp", reference=reference,
                          coding="UTF8", smsFor=kind.name, isReceived=False, isSMSSend=False, channel="WHATSAPP",
                          invoice_id=invoice_id, logsId=logs_id)
    db.flush()
    # auto=False: SMS inaandaliwa tu (inasubiri "Tuma"). SMS_AUTO_SEND=false kwenye .env inazuia kutuma kwa zote.
    if config.SMS_AUTO_SEND and auto is not False:
        db.info.setdefault(_AUTO_KEY, []).append(sms.id)
        if twin is not None:
            db.info[_AUTO_KEY].append(twin.id)
    if commit:
        dao.commit(sms)
    return sms


@event.listens_for(Session, "after_commit")
def _send_after_commit(session: Session) -> None:
    ids = session.info.pop(_AUTO_KEY, None)
    if ids:
        tenant.spawn(send_pending_ids, list(ids))


@event.listens_for(Session, "after_rollback")
def _forget_after_rollback(session: Session) -> None:
    session.info.pop(_AUTO_KEY, None)


def send_pending_ids(ids) -> int:
    """Inatuma SMS zilizoandaliwa (thread ya nyuma). Zikishindikana zinabaki 'zinasubiri'."""
    from ..db import session_scope  # import ya ndani kuepuka mzunguko

    sent = 0
    with session_scope() as db:
        dao = SmsDao(db)
        for sms_id in ids:
            sms = dao.get(sms_id)
            if sms is None or sms.isSMSSend:
                continue
            try:
                deliver(sms)
            except AppError as error:
                logger.warning("Auto %s %s not sent: %s", sms.channel, sms_id, error.detail)
                dao.update(sms, error=error.detail[:300])
                continue
            dao.update(sms, isSMSSend=True, error=None)
            sent += 1
    return sent


def retry_recent_pending(hours: int = 24) -> int:
    """Scheduler: kujaribu tena SMS za karibuni zilizoshindikana (mf. mtandao ulikatika)."""
    if not config.SMS_AUTO_SEND:
        return 0
    from ..db import session_scope

    from ..core.base_model import utc_now

    since = utc_now() - timedelta(hours=hours)
    with session_scope() as db:
        ids = [s.id for s in SmsDao(db).pending_since(since)]
    return send_pending_ids(ids) if ids else 0


# ------------------------------------------------------------------- gateway
def deliver(sms: Sms) -> None:
    """Inatuma kwa njia ya ujumbe huu (SMS au WhatsApp)."""
    if (sms.channel or "SMS") == "WHATSAPP":
        from ..core import whatsapp

        sms.gatewayId = whatsapp.send_text(sms.msisdn, sms.text) or sms.gatewayId
        sms.deliveryStatus = "SENT"
    else:
        _send_to_gateway(sms)


_GATEWAY_STATE: dict[str, dict] = {}


def _alt_msisdn(msisdn: str) -> str:
    return msisdn[1:] if msisdn.startswith("+") else f"+{msisdn}"


def safe_reference(reference: str | None) -> str:
    """
    FastHub inakataa reference fupi ("must be at least 20 characters long"): reference fupi inaongezewa
    herufi za kipekee hadi ifikie SMS_REFERENCE_MIN_LENGTH (kawaida 20).
    """
    import secrets

    ref = "".join(c for c in (reference or "SMS") if c.isalnum() or c in "-_")[:60] or "SMS"
    need = max(config.SMS_REFERENCE_MIN_LENGTH, 0)
    if len(ref) < need:
        ref = f"{ref}-{secrets.token_hex(16)}"[:max(need, len(ref) + 9)]
    return ref


def response_balance(response) -> float | None:
    """Salio lililo kwenye jibu la FastHub ({"balance": 236250.0}); None kama halipo."""
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("balance") is not None and not isinstance(body["balance"], bool):
            return float(str(body["balance"]).replace(",", ""))
    except Exception:
        pass
    return None


def _remember_balance(response) -> None:
    """FastHub inarudisha "balance" kwenye kila jibu - tunaikumbuka kama salio la gateway."""
    value = response_balance(response)
    if value is not None:
        from .credit import remember_gateway_balance

        remember_gateway_balance(value)


# Firewall ya FastHub (Cloudflare) inaweza kuzuia maombi yenye User-Agent ya "python-requests" (403 ya HTML).
GATEWAY_HEADERS = {"User-Agent": f"{''.join(c for c in config.PLATFORM_NAME if c.isalnum()) or 'LogisticCloud'}/1.0"
                                 + (f" (+https://{config.PLATFORM_DOMAIN})" if config.PLATFORM_DOMAIN else ""),
                   "Accept": "application/json"}


def _post_gateway(text: str, msisdn: str, reference: str):
    payload = {
        "auth": {"clientId": config.SMS_CLIENT_ID, "clientSecret": config.SMS_CLIENT_SECRET},
        "messages": [{"text": text, "msisdn": msisdn, "source": config.SMS_SOURCE_NAME,
                      "reference": reference, "coding": config.SMS_CODING}],
    }
    url = gateway_url(config.SMS_API)
    try:
        # allow_redirects=False: redirect (mf. http -> https) inageuza POST kuwa GET, na FastHub hujibu
        # "Health check successful. Use POST..." bila kutuma SMS. Tunakataa redirect waziwazi badala yake.
        response = requests.post(url, json=payload, timeout=20, headers=GATEWAY_HEADERS, allow_redirects=False)
    except requests.RequestException as error:
        logger.warning("SMS gateway unreachable: %s", error)
        raise AppError(f"SMS gateway unreachable: {error}")
    if getattr(response, "status_code", 200) in (301, 302, 303, 307, 308):
        target = (getattr(response, "headers", {}) or {}).get("location", "?")
        gateway_logger.warning("FastHub redirect %s -> %s", url, target)
        raise AppError(f"SMS_API inaelekezwa (redirect {response.status_code}) kwenda {target}. "
                       f"Weka anwani hiyo kamili kwenye .env (SMS_API), kisha washa upya backend")
    _remember_balance(response)
    gateway_logger.info("FastHub -> %s ref=%s | %s", msisdn, reference, response_dump(response))
    return response


def gateway_url(url: str | None) -> str:
    """FastHub inapatikana kwa https tu: http:// ingeelekezwa (redirect) na POST ingegeuka GET."""
    url = (url or "").strip()
    if url.startswith("http://") and "fasthub" in url:
        url = "https://" + url[len("http://"):]
    return url


# Kila jibu la FastHub (kamili) kwa uchunguzi: `journalctl -u logisticcore | grep FastHub`
gateway_logger = logging.getLogger("logistic.sms.gateway")
_DUMP_HEADERS = ("date", "content-type", "server", "cf-ray", "cf-cache-status", "x-request-id", "retry-after")


def response_dump(response, limit: int = 2000) -> str:
    """Jibu la gateway kama maandishi: status, headers muhimu na body (bila siri zetu - hazimo kwenye jibu)."""
    try:
        headers = getattr(response, "headers", {}) or {}
        head = ", ".join(f"{k}={headers.get(k)}" for k in _DUMP_HEADERS if headers.get(k))
        body = (getattr(response, "text", "") or "").replace("\n", " ").strip()
        return f"HTTP {getattr(response, 'status_code', '?')} [{head}] {body[:limit]}"
    except Exception as error:  # usiharibu kutuma kwa sababu ya log
        return f"(haikusomeka: {error})"


def _rejected(response) -> bool:
    """Jibu la 200 lenye "status": false / "success": false = gateway imekataa ujumbe."""
    try:
        body = response.json()
    except Exception:
        return False
    if not isinstance(body, dict):
        return False
    # FastHub ikikubali: {"status": true, "message": "Successfully submitted ..."}. Kitu kingine chochote
    # (mf. GET: {"status": "ok", "message": "Health check successful. Use POST ..."}) = SMS HAIJATUMWA.
    for key in ("status", "success"):
        if key not in body:
            continue
        v = body.get(key)
        if v is True or (isinstance(v, str) and v.strip().lower() in ("true", "success", "successful", "submitted")):
            return False
        return True
    return "health check" in str(body.get("message", "")).lower()


def _balance_note(response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("balance") is not None and float(body["balance"]) <= 0:
            return " - salio la FastHub ni 0, ongeza salio / FastHub balance is 0"
    except Exception:
        pass
    return ""


def _gateway_reason(response) -> str:
    """Maelezo ya gateway kwa nini imekataa (bila siri), ili yaonekane kwenye app."""
    try:
        body = response.json()
    except Exception:
        raw = (getattr(response, "text", "") or "").strip()
        if raw.lower().startswith(("<!doctype", "<html")) or "<html" in raw[:300].lower():
            # ukurasa wa HTML (mf. Cloudflare "Sorry, you have been blocked"): si jibu la API
            if getattr(response, "status_code", 0) in (403, 429, 503):
                return ("firewall ya FastHub imezuia ombi kutoka mtandao/IP hii. Jaribu baadaye au waombe FastHub "
                        "waruhusu IP ya server yako / FastHub firewall blocked this network")
            return "gateway imerudisha ukurasa wa HTML badala ya jibu la API (hakiki SMS_API)"
        return raw[:200]
    if isinstance(body, dict) and "health check" in str(body.get("message", "")).lower():
        return ("FastHub ilipokea ombi la GET badala ya POST (Health check), kwa hiyo SMS haikutumwa. "
                "Hakiki SMS_API kwenye .env iwe https://bulksms.fasthub.co.tz/api/sms/send")
    if isinstance(body, dict):
        # FastHub: {"message": "Validation errors", "data": [{"reference": " must be at least 20 characters long"}]}
        details = []
        for item in body.get("data") or [] if isinstance(body.get("data"), list) else []:
            if isinstance(item, dict):
                details += [f"{k}{v if str(v).startswith(' ') else ' ' + str(v)}" for k, v in item.items()]
        if details:
            return f"{body.get('message') or 'Validation errors'}: {'; '.join(details)}"[:200]
        for k in ("message", "error", "description", "reason", "detail", "status_description", "msg"):
            v = body.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()[:200]
            if isinstance(v, dict):
                inner = v.get("message") or v.get("description")
                if isinstance(inner, str):
                    return inner.strip()[:200]
    return str(body)[:200]


def _send_to_gateway(sms: Sms) -> None:
    if not (config.SMS_CLIENT_ID and config.SMS_CLIENT_SECRET):
        raise AppError("SMS gateway is not configured (SMS_CLIENT_ID / SMS_CLIENT_SECRET in .env)")
    from ..core.phone import error_message, for_gateway

    msisdn = for_gateway(sms.msisdn)
    if msisdn is None:
        raise AppError(error_message(sms.msisdn))
    # reference ya kipekee kwa kila ujumbe, ili ripoti ya kufika (DLR) itambue ujumbe husika
    if config.SMS_DLR_UNIQUE_REFERENCE and sms.id is not None:  # (SMS za muda kama OTP hazina id)
        sms.gatewayRef = sms.gatewayRef or sms.id.hex
    reference = safe_reference(sms.gatewayRef or sms.reference)
    if sms.id is not None:
        sms.gatewayRef = reference  # DLR inarudisha reference hii
    # Kama gateway imeshakubali namba bila/na "+" (tazama chini), tumia muundo huo moja kwa moja.
    from .credit import account_key

    state = _GATEWAY_STATE.setdefault(account_key(), {})  # kila akaunti ya FastHub ina muundo wake
    first = _alt_msisdn(msisdn) if state.get("altMsisdn") else msisdn
    response = _post_gateway(sms.text, first, reference)
    if response.status_code == 400:
        # 400 = gateway imekataa ombi. Sababu inayojulikana zaidi ni muundo wa namba (+255... dhidi ya 255...):
        # jaribu mara moja kwa muundo mwingine; ukifaulu, unakumbukwa kwa SMS zinazofuata.
        retry = _post_gateway(sms.text, _alt_msisdn(first), reference)
        if retry.status_code == 200:
            state["altMsisdn"] = not state.get("altMsisdn", False)
            logger.warning("SMS gateway accepted msisdn %s (not %s): set SMS_MSISDN_PLUS=%s in .env",
                           _alt_msisdn(first), first, "true" if _alt_msisdn(first).startswith("+") else "false")
            response = retry
    if sms.id is not None:
        # jibu kamili (kwa uchunguzi / FastHub support). Kampuni inayotumia akaunti yako haioni salio lako.
        from .credit import own_account

        dump = response_dump(response)
        if not own_account():
            import re as _re

            dump = _re.sub(r'("?(?:balance|credit|credits)"?\s*[:=]\s*)"?[0-9]+(?:[.,][0-9]+)*"?', r"\1***", dump, flags=_re.I)
        sms.gatewayResponse = dump
    if response.status_code != 200:
        body = _gateway_reason(response)
        logger.warning("SMS gateway error %s for %s: %s", response.status_code, first, body)
        raise AppError(f"SMS not sent (gateway status {response.status_code}{': ' + body if body else ''})"
                       f"{_balance_note(response)}")
    if _rejected(response):
        # FastHub inaweza kujibu 200 lakini {"status": false, ...} (mf. salio halitoshi): SMS HAIJATUMWA
        body = _gateway_reason(response)
        logger.warning("SMS gateway rejected message for %s: %s", first, body)
        raise AppError(f"SMS not sent (gateway: {body or 'status false'}){_balance_note(response)}")
    from ..core.base_model import utc_now
    from .broadcast import segments

    sms.deliveryStatus = "SENT"
    sms.sentAt = utc_now()
    sms.parts = segments(sms.text or "")
    balance = response_balance(response)
    from .credit import own_account

    if balance is not None and own_account():
        # inahifadhiwa na ujumbe: salio linabaki hata backend ikiwashwa upya (akaunti ya kampuni yenyewe tu -
        # salio la akaunti yako halionyeshwi kwa kampuni zinazoitumia)
        sms.balanceAfter = balance
    try:
        from .dlr import gateway_message_id

        sms.gatewayId = gateway_message_id(response.json()) or sms.gatewayId
    except Exception:  # jibu lisilo JSON: id ya gateway haipo, reference yetu inatosha
        pass


# ---------------------------------------------------------------- use cases
def search(db: Session, f: schema.Search):
    since = None
    if f.days:
        from ..core.base_model import utc_now

        since = utc_now() - timedelta(days=max(f.days, 1))
    limit = min(f.limit, 5000) if f.limit else None
    return SmsDao(db).search(f.smsFor, f.isReceived, f.isSMSSend, f.channel, f.deliveryStatus, since, limit)


def send(db: Session, data: schema.SendFrom) -> Sms:
    dao = SmsDao(db)
    sms = dao.get(data.id)
    if sms is None:
        raise NotFound("The SMS does not exist")
    if data.text:
        sms.text = data.text
    try:
        deliver(sms)  # ikishindikana, SMS haiwekwi kama imetumwa
    except AppError as error:
        dao.update(sms, error=error.detail[:300])
        raise
    if (sms.channel or "SMS") == "WHATSAPP":
        return dao.update(sms, isSMSSend=True, error=None)
    return dao.update(sms, isSMSSend=True, error=None, source=config.SMS_SOURCE_NAME, coding=config.SMS_CODING)


def resend(db: Session, data: schema.Resend, user_id) -> Sms:
    """
    Kutuma tena: nakala mpya ya ujumbe (aina, ankara, maandishi) inaundwa na kutumwa sasa hivi.
    Ujumbe wa awali haubadilishwi, kwa hiyo historia inaonyesha mara zote mbili.
    """
    from ..core.phone import try_normalize

    dao = SmsDao(db)
    original = dao.get(data.id)
    if original is None:
        raise NotFound("The SMS does not exist")
    text = (data.text or "").strip() or original.text
    msisdn = original.msisdn
    if data.msisdn and data.msisdn.strip():
        msisdn = try_normalize(data.msisdn)
        if msisdn is None:
            from ..core.phone import error_message

            raise BadRequest(error_message(data.msisdn))
    copy = dao.create(text=text, msisdn=msisdn, source=original.source or config.SMS_SOURCE_NAME,
                      reference=original.reference, coding=original.coding or config.SMS_CODING,
                      smsFor=original.smsFor, isReceived=False, isSMSSend=False,
                      channel=original.channel or "SMS", invoice_id=original.invoice_id, logsId=user_id)
    try:
        deliver(copy)
    except AppError as error:
        dao.update(copy, error=f"(tuma tena) {error.detail}"[:300])
        raise
    return dao.update(copy, isSMSSend=True, error=None)


def delete(db: Session, sms_id) -> bool:
    dao = SmsDao(db)
    sms = dao.get(sms_id)
    if sms is None:
        raise NotFound("The SMS does not exist")
    return dao.delete(sms)
