from sqlalchemy.orm import Session

from .. import config
from ..core.base_model import utc_now
from ..core.enums import EInvoiceStatus, ESmsStatus
from ..core.exceptions import BadRequest, Conflict, NotFound
from ..core.utils import join_ids, product_cbm, random_box_key, split_ids, stamp
from ..invoice.dao import InvoiceDao
from ..product.dao import ProductDao
from ..sms import service as sms_service
from ..sms.schema import StoreDetails
from . import schema
from .dao import PackageDao
from .model import Package


def _get_or_404(dao: PackageDao, package_id) -> Package:
    package = dao.get(package_id)
    if package is None:
        raise NotFound("Package not found...")
    return package


def _unique_box_id(dao: PackageDao) -> str:
    while True:
        key = random_box_key()
        if dao.by_box_id(key) is None:
            return key


def create(db: Session, data: schema.Insert, current_user_id) -> Package:
    dao = PackageDao(db)
    return dao.create(boxId=_unique_box_id(dao), packageType=data.packageType.strip().upper() or "GENERAL",
                      weight=data.weight, trackNumber=data.trackNumber, productList="", invoiceList="",
                      isCollect=False, isBoxClose=False, logsId=current_user_id)


def add_product(db: Session, data: schema.AddProduct) -> Package:
    dao = PackageDao(db)
    package = _get_or_404(dao, data.packageId)
    if package.isBoxClose:
        raise BadRequest("This package is already closed")
    if InvoiceDao(db).get(data.invoiceId) is None:
        raise NotFound("Invoice not found...")
    product = ProductDao(db).get(data.productId)
    if product is None:
        raise NotFound("Product not found...")
    box_carrier = (package.packageType or "").upper()
    if box_carrier in ("AIR", "SEA") and (product.carrierType or "AIR").upper() != box_carrier:
        kind = "container (SEA)" if box_carrier == "SEA" else "box (AIR)"
        raise BadRequest(f"This {kind} only accepts {box_carrier} cargo")
    if dao.containing_product(data.productId):
        raise Conflict("Product already added...")

    products = split_ids(package.productList) + [str(data.productId)]
    invoices = split_ids(package.invoiceList)
    if str(data.invoiceId) not in invoices:
        invoices.append(str(data.invoiceId))
    return dao.update(package, weight=(package.weight or 0) + data.productWeight,
                      productList=join_ids(products), invoiceList=join_ids(invoices))


def remove_product(db: Session, data: schema.RemoveProduct) -> Package:
    """Kutoa bidhaa kwenye box ambalo bado halijafungwa."""
    dao = PackageDao(db)
    package = _get_or_404(dao, data.packageId)
    if package.isBoxClose:
        raise BadRequest("This package is already closed")
    products = split_ids(package.productList)
    if str(data.productId) not in products:
        raise NotFound("Product is not in this package")
    products.remove(str(data.productId))
    product = ProductDao(db).get(data.productId)
    weight = max((package.weight or 0) - ((product.weight or 0) if product else 0), 0.0)
    # invoice inabaki kwenye orodha kama bado ina bidhaa nyingine ndani ya box hili
    invoices = []
    for invoice_id in split_ids(package.invoiceList):
        invoice = InvoiceDao(db).with_details(invoice_id)
        if invoice and any(str(p.id) in products for p in invoice.product):
            invoices.append(invoice_id)
    return dao.update(package, weight=weight, productList=join_ids(products), invoiceList=join_ids(invoices))


def _update_invoices(db: Session, package: Package, status: str, history: str | None) -> list:
    dao = InvoiceDao(db)
    history = history or stamp(status)
    invoices = []
    for invoice_id in split_ids(package.invoiceList):
        invoice = dao.get(invoice_id)
        if invoice is None:
            raise NotFound(f"Invoice {invoice_id} not found")
        invoices.append(dao.change_status(invoice, status, history, commit=False))
    return invoices


_NO_TRACK = ("", "NO QRCODE NO BARCODE")


def _track_prefix(db: Session) -> str:
    """Kiambishi cha track number = code ya kampuni (slug) kwa herufi kubwa, mf. ACME. Kila kampuni ina chake."""
    import re

    from ..core import tenant

    slug = tenant.state().slug
    cid = tenant.company_id()
    if not slug and cid is not None:
        from ..saas.company.model import Company

        with tenant.system():
            company = db.get(Company, cid)
            slug = company.slug if company else None
    code = re.sub(r"[^A-Z0-9]", "", (slug or "").upper())[:8]
    return code or "TRK"


def next_track(db: Session, package: Package) -> str:
    """
    Track number ya safari inayotengenezwa na mfumo: <CODE YA KAMPUNI>-<A ndege / S meli><yymmdd>-<namba ya siku>,
    mf. ACME-A261110-001. Ni ya kipekee ndani ya kampuni (inaruka zilizotumika).
    """
    from ..core.utils import local_now

    prefix = f"{_track_prefix(db)}-{'S' if carrier_of(db, package) == 'SEA' else 'A'}{local_now():%y%m%d}-"
    dao = PackageDao(db)
    n = db.query(Package).filter(Package.trackNumber.like(f"{prefix}%")).count() + 1
    while True:
        track = f"{prefix}{n:03d}"
        other = dao.by_track_number(track)
        if other is None or other.id == package.id:
            return track
        n += 1


def suggest_track(db: Session, package_id) -> dict:
    package = _get_or_404(PackageDao(db), package_id)
    current = (package.trackNumber or "").strip()
    return {"trackNumber": current if current not in _NO_TRACK else next_track(db, package),
            "generated": current in _NO_TRACK}


def close(db: Session, data: schema.ClosePackage, user_id=None) -> Package:
    """Box linafungwa na kusafirishwa: invoice zote zinabadilishwa hali na wateja wanapata SMS."""
    dao = PackageDao(db)
    package = _get_or_404(dao, data.id)
    track = data.trackNumber.strip()
    if track.upper() in _NO_TRACK:
        track = next_track(db, package)  # mfumo unatengeneza track number ya safari
    other = dao.by_track_number(track)
    if other and other.id != package.id:
        raise Conflict("Track Number is exited...")

    invoice_ids = [i.id for i in _update_invoices(db, package, data.status, data.history)]
    eta = data.eta or default_eta(db, package)
    package = dao.update(package, weight=data.productWeight, trackNumber=track, isBoxClose=data.isBoxClose,
                         shippedAt=utc_now(), eta=eta)
    from ..notification.service import notify

    notify(db, "STORE", "select", kind="BOX_SHIPPED", title=f"Box {package.boxId} limesafirishwa",
           body=f"Track {track} · mizigo {len(split_ids(package.productList))} · kilo {package.weight or 0:,.1f}",
           link=f"box:{package.id}")
    _notify(db, invoice_ids, ESmsStatus.SHIPPING, package.logsId, split_ids(package.productList), eta=package.eta)
    if data.isBoxClose:
        from ..demand.service import raise_for

        raise_for(db, "BOX_CLOSED", package, user_id)
    return package


def mark_collected(db: Session, data: schema.MarkCollected, user_id=None) -> Package:
    """
    Box limefika stoo: invoice zinabadilishwa hali. SMS za "mzigo umefika" zinatumwa tu kama sendSms=True;
    vinginevyo mtumiaji anazituma baadaye kwa mmoja mmoja au kwa wote (notify_store).
    """
    dao = PackageDao(db)
    package = _get_or_404(dao, data.id)
    invoice_ids = [i.id for i in _update_invoices(db, package, data.status, data.history)]
    package = dao.update(package, isCollect=data.isCollect, arrivedAt=utc_now() if data.isCollect else None)
    from ..notification.service import notify

    notify(db, "PAYMENT", "insert", kind="BOX_ARRIVED", title=f"Box {package.boxId} limefika stoo",
           body=f"Ankara {len(invoice_ids)} ziko tayari kutolewa na kulipwa", link=f"box:{package.id}")
    if data.sendSms:
        _notify(db, invoice_ids, ESmsStatus.STORE, package.logsId, split_ids(package.productList))
    else:
        db.commit()
    if data.isCollect:
        from ..demand.service import raise_for

        raise_for(db, "BOX_ARRIVED", package, user_id)
    return package


def arrivals(db: Session, package_id) -> dict:
    """Ankara zilizo ndani ya box (mteja, mpokeaji, mizigo, pesa) na kama SMS ya "mzigo umefika" imetumwa."""
    from sqlalchemy import func

    from ..sms.model import Sms

    package = _get_or_404(PackageDao(db), package_id)
    wanted = {str(i) for i in split_ids(package.productList)}
    dao = InvoiceDao(db)
    rows = []
    for invoice_id in split_ids(package.invoiceList):
        invoice = dao.with_details(invoice_id)
        if invoice is None:
            continue
        products = [p for p in invoice.product if str(p.id) in wanted]
        if not products:
            continue
        customer = invoice.customer[0] if invoice.customer else None
        receiver = invoice.receiver[0] if invoice.receiver else None
        q = db.query(func.count(Sms.id), func.max(Sms.created_at)).filter(
            Sms.invoice_id == invoice.id, Sms.smsFor == ESmsStatus.STORE.name)
        if package.arrivedAt:
            q = q.filter(Sms.created_at >= package.arrivedAt)
        sms_count, last_sms = q.one()
        rows.append({
            "invoiceId": str(invoice.id), "invoiceNumber": invoice.invoiceNumber, "status": invoice.status,
            "customer": {"name": customer.name, "phone": customer.phoneNumber} if customer else None,
            "receiver": {"name": receiver.name, "phone": receiver.phoneNumber} if receiver else None,
            "items": len(products), "cartons": sum(p.quantities or 0 for p in products),
            "kg": round(sum(p.weight or 0 for p in products), 2),
            "amount": round(sum(p.unitPrice or 0 for p in products)),
            "officeCodes": [p.officeCode for p in products if p.officeCode],
            "descriptions": ", ".join(p.description for p in products)[:200],
            "smsSent": int(sms_count or 0), "lastSmsAt": last_sms.isoformat() if last_sms else None,
        })
    rows.sort(key=lambda r: (r["smsSent"] > 0, (r["customer"] or {}).get("name") or ""))
    return {"id": str(package.id), "boxId": package.boxId, "isCollect": package.isCollect,
            "arrivedAt": package.arrivedAt.isoformat() if package.arrivedAt else None,
            "invoices": rows, "pending": sum(1 for r in rows if r["smsSent"] == 0)}


def notify_store(db: Session, package_id, data: schema.NotifyStore, user_id) -> dict:
    """Kutuma SMS ya "mzigo umefika" kwa ankara zilizochaguliwa (au zote) za box hili, sasa hivi."""
    from ..sms.broadcast import dispatch

    sms_service.ensure_enabled(db, ESmsStatus.STORE)
    package = _get_or_404(PackageDao(db), package_id)
    if not package.isCollect:
        raise BadRequest("Box bado halijapokelewa stoo")
    inside = [str(i) for i in split_ids(package.invoiceList)]
    chosen = inside if not data.invoiceIds else [str(i) for i in data.invoiceIds if str(i) in inside]
    if not chosen:
        raise BadRequest("Chagua ankara zilizo ndani ya box hili")
    ids = _notify(db, chosen, ESmsStatus.STORE, user_id, split_ids(package.productList),
                  to_receiver=data.toReceiver, auto=False)
    if ids:
        dispatch(ids)  # kutuma sasa hivi (kwa nyuma), bila kujali SMS_AUTO_SEND
    return {"invoices": len(chosen), "messages": len(ids)}


def arrivals_excel(db: Session, package_id) -> tuple[bytes, str]:
    from ..core import excel

    data = arrivals(db, package_id)
    rows = [[r["invoiceNumber"], (r["customer"] or {}).get("name"), (r["customer"] or {}).get("phone"),
             (r["receiver"] or {}).get("name"), (r["receiver"] or {}).get("phone"), r["descriptions"],
             ", ".join(r["officeCodes"]), r["cartons"], r["kg"], r["amount"],
             "Ndiyo" if r["smsSent"] else "Hapana"] for r in data["invoices"]]
    content = excel.build([excel.Sheet(
        f"Box {data['boxId']}",
        ["Ankara", "Mteja", "Simu", "Mpokeaji", "Simu ya mpokeaji", "Mizigo", "Code za ofisi", "Katoni",
         "Kilo", "Kiasi (TSh)", "SMS imetumwa"],
        rows, money={9}, totals={7, 8, 9},
        subtitle=f"Mizigo iliyofika - box {data['boxId']}")])
    return content, f"box_{data['boxId']}_mizigo"



def _notify(db: Session, invoice_ids: list, kind: ESmsStatus, logs_id, product_ids=None, eta=None,
            to_receiver: bool = True, auto: bool | None = None) -> list:
    """
    SMS moja kwa kila invoice (si kwa kila bidhaa):
      - SHIPPING: mteja anajulishwa mzigo umeondoka.
      - STORE: mteja (na mpokeaji kama ni mtu mwingine) anajulishwa mzigo umefika na kiasi cha kulipa.
    """
    wanted = {str(i) for i in product_ids} if product_ids else None
    dao = InvoiceDao(db)
    created = []
    for invoice_id in invoice_ids:
        invoice = dao.with_details(invoice_id)
        if invoice is None:
            continue
        products = [p for p in invoice.product if wanted is None or str(p.id) in wanted]
        if not products:
            continue
        customer = invoice.customer[0] if invoice.customer else None
        receiver = invoice.receiver[0] if invoice.receiver else None
        reference = str(invoice.id)

        if kind == ESmsStatus.SHIPPING:
            if customer is not None:
                sms = sms_service.queue(db, kind, text=sms_service.shipping_message(products, customer.name, invoice.invoiceNumber, eta),
                                        msisdn=customer.phoneNumber, reference=reference, invoice_id=invoice.id,
                                        logs_id=logs_id, commit=False, auto=auto)
                if sms is not None:
                    created.append(sms)
            continue

        usd = 0.0
        for p in products:
            price = p.price[0] if p.price else None
            cost = (price.cost if price else 0.0) or 0
            per = (price.weight if price else 0) or 1  # bei ni ya "kiasi hiki" (mf. 1 kg / 1 CBM)
            qty = product_cbm(p) if price is not None and (price.unit or "KG").upper() == "CBM" else (p.weight or 0)
            usd += qty / per * cost
        people = [x for x in (customer, receiver if to_receiver else None) if x is not None]
        seen = set()
        for person in people:
            if not person.phoneNumber or person.phoneNumber in seen:
                continue  # asiye na namba hatumiwi SMS
            seen.add(person.phoneNumber)
            text = sms_service.store_message(StoreDetails(
                name=person.name,
                quantity=sum(p.quantities or 0 for p in products),
                amount=sum(p.unitPrice or 0 for p in products),
                kg=sum(p.weight or 0 for p in products),
                usd=usd,
                invoiceNumber=invoice.invoiceNumber,
                items=sms_service.items_block(products, with_code=True),
                totals=sms_service.totals_line(products),
                hasCodes=any(p.officeCode for p in products)))
            sms = sms_service.queue(db, kind, text=text, msisdn=person.phoneNumber, reference=reference,
                                    invoice_id=invoice.id, logs_id=logs_id, commit=False, auto=auto)
            if sms is not None:
                created.append(sms)
    db.flush()
    ids = [s.id for s in created]
    db.commit()
    return ids


# ---------------------------------------------------------------- ETA (tarehe ya kutarajia kufika)
def carrier_of(db: Session, package: Package) -> str:
    """SEA kama ni container ya meli (au bidhaa zake ni za meli), la sivyo AIR."""
    kind = (package.packageType or "").upper()
    if kind in ("AIR", "SEA"):
        return kind
    for product_id in split_ids(package.productList):
        product = ProductDao(db).get(product_id)
        if product is not None and (product.carrierType or "").upper() == "SEA":
            return "SEA"
    return "AIR"


def default_eta(db: Session, package: Package):
    from datetime import timedelta

    days = config.ETA_SEA_DAYS if carrier_of(db, package) == "SEA" else config.ETA_AIR_DAYS
    return (utc_now() + timedelta(days=max(days, 0))).date()


def set_eta(db: Session, package_id, data: schema.SetEta, user_id) -> Package:
    """Kubadilisha ETA ya box lililo safarini; hiari: kuwajulisha wateja wake kwa SMS."""
    dao = PackageDao(db)
    package = _get_or_404(dao, package_id)
    if not package.isBoxClose or package.isCollect:
        raise BadRequest("ETA inawekwa kwa box lililo safarini tu")
    old = package.eta
    if data.notify:
        sms_service.ensure_enabled(db, ESmsStatus.ETA)
    package = dao.update(package, eta=data.eta)
    if data.notify and old != data.eta:
        _notify_eta(db, package, data.reason, user_id)
    return package


def _notify_eta(db: Session, package: Package, reason: str | None, user_id) -> int:
    dao = InvoiceDao(db)
    sent = 0
    for invoice_id in split_ids(package.invoiceList):
        invoice = dao.with_details(invoice_id)
        customer = invoice.customer[0] if invoice and invoice.customer else None
        if customer is None:
            continue
        why = f" {reason.strip()}." if reason and reason.strip() else ""
        text = (f"Habari {customer.name}, mzigo wako wa ankara #{invoice.invoiceNumber} sasa unatarajiwa kufika "
                f"Tanzania tarehe {package.eta:%d/%m/%Y}.{why} Samahani kwa usumbufu. Tupigie: {config.COMPANY_PHONES}")
        if sms_service.queue(db, ESmsStatus.ETA, text=text, msisdn=customer.phoneNumber, reference=str(invoice.id),
                             invoice_id=invoice.id, logs_id=user_id, commit=False):
            sent += 1
    db.commit()
    return sent


def late(db: Session) -> list[dict]:
    """Mabox yaliyo safarini ambayo ETA yake imepita."""
    today = utc_now().date()
    rows = (db.query(Package).filter(Package.isBoxClose.is_(True), Package.isCollect.is_(False),
                                     Package.eta.isnot(None), Package.eta < today)
            .order_by(Package.eta).all())
    return [{"id": str(p.id), "boxId": p.boxId, "packageType": p.packageType, "trackNumber": p.trackNumber,
             "eta": p.eta.isoformat(), "daysLate": (today - p.eta).days,
             "shippedAt": p.shippedAt.isoformat() if p.shippedAt else None,
             "invoices": len(split_ids(p.invoiceList)), "products": len(split_ids(p.productList))} for p in rows]


def alert_late() -> None:
    """Scheduler: taarifa kwa wenye ruhusa ya Stoo kwa kila box lililochelewa (mara moja kwa siku)."""
    from ..db import session_scope
    from ..notification.service import notify

    with session_scope() as db:
        for box in late(db):
            notify(db, "STORE", "select", kind="BOX_LATE", title=f"Box {box['boxId']} limechelewa siku {box['daysLate']}",
                   body=f"Lilitarajiwa {box['eta']} · track {box['trackNumber']} · ankara {box['invoices']}",
                   link=f"box:{box['id']}", dedupe_hours=22)
        db.commit()


def by_flags(db: Session, is_collect: bool, is_box_close: bool):
    return PackageDao(db).by_flags(is_collect, is_box_close)


def list_all(db: Session):
    return PackageDao(db).all_ordered()


def delete(db: Session, package_id) -> bool:
    dao = PackageDao(db)
    package = _get_or_404(dao, package_id)
    if package.isBoxClose:
        raise BadRequest("A closed (shipped) package cannot be deleted")
    return dao.delete(package)


# ------------------------------------------------------------- kwa app (orodha zenye maelezo kamili)
def _product_row(product, invoice) -> dict:
    customer = invoice.customer[0] if invoice and invoice.customer else None
    receiver = invoice.receiver[0] if invoice and invoice.receiver else None
    return {
        "id": str(product.id),
        "description": product.description,
        "trackNumber": product.trackNumber,
        "carrierType": product.carrierType,
        "weight": product.weight,
        "quantities": product.quantities,
        "unitPrice": product.unitPrice,
        "cbm": round(product_cbm(product), 4),
        "path": product.path,
        "invoiceId": str(invoice.id) if invoice else None,
        "invoiceNumber": invoice.invoiceNumber if invoice else None,
        "officeCode": product.officeCode,
        "invoiceStatus": invoice.status if invoice else None,
        "customerName": customer.name if customer else None,
        "customerPhone": customer.phoneNumber if customer else None,
        "receiverName": receiver.name if receiver else None,
        "receiverPhone": receiver.phoneNumber if receiver else None,
    }


def available_products(db: Session) -> list[dict]:
    packed = set()
    for package in PackageDao(db).all():
        packed.update(split_ids(package.productList))
    rows = []
    for invoice in InvoiceDao(db).with_details_by_status(EInvoiceStatus.PARKING.name):
        for product in invoice.product:
            if str(product.id) not in packed:
                rows.append(_product_row(product, invoice))
    return rows


def products_in(db: Session, package_id) -> list[dict]:
    package = _get_or_404(PackageDao(db), package_id)
    invoices = {}
    dao = InvoiceDao(db)
    for invoice_id in split_ids(package.invoiceList):
        invoice = dao.with_details(invoice_id)
        if invoice is not None:
            invoices[str(invoice.id)] = invoice
    wanted = split_ids(package.productList)
    rows = []
    for invoice in invoices.values():
        for product in invoice.product:
            if str(product.id) in wanted:
                rows.append(_product_row(product, invoice))
    rows.sort(key=lambda r: wanted.index(r["id"]))
    return rows


# ------------------------------------------------------------- manifest na lebo
def manifest_pdf(db: Session, package_id) -> tuple[bytes, str]:
    from ..core import pdf

    package = _get_or_404(PackageDao(db), package_id)
    return pdf.manifest(package, products_in(db, package_id)), f"manifest_{package.boxId}"


def _label(row: dict, box_id: str | None, carrier: str | None, n: int = 1, of: int = 1) -> dict:
    who = row.get("receiverName") or row.get("customerName") or "-"
    phone = row.get("receiverPhone") or row.get("customerPhone") or ""
    lines = [f"Ankara: {row.get('invoiceNumber') or '-'}", f"Simu: {phone}",
             f"{row.get('description') or ''}"[:32], f"Kilo: {row.get('weight') or 0:,.1f}"]
    if row.get("cbm"):
        lines.append(f"CBM: {row['cbm']:,.3f}")
    if box_id:
        lines.append(f"Box: {box_id}")
    return {
        # QR = code ya ofisi (kuskani lebo kunapata mzigo huu: picha, kupanga box, kukabidhi)
        "qr": row.get("officeCode") or row.get("trackNumber") or row.get("invoiceNumber") or row.get("id"),
        "title": row.get("trackNumber") or f"#{row.get('invoiceNumber')}",
        "subtitle": who,
        "lines": lines,
        "badge": f"{'MELI' if (carrier or row.get('carrierType') or '').upper() == 'SEA' else 'NDEGE'}"
                 + (f" {n}/{of}" if of > 1 else ""),
        "footer": f"{config.COMPANY_ORIGIN} -> Tanzania · {config.COMPANY_PHONES}",
        "code": row.get("officeCode"),
    }


def _expand(rows: list[dict], box_id, carrier, per_carton: bool) -> list[dict]:
    items = []
    for row in rows:
        count = int(row.get("quantities") or 1) if per_carton else 1
        count = max(1, min(count, 200))
        for n in range(1, count + 1):
            items.append(_label(row, box_id, carrier, n, count))
    return items


def labels_pdf(db: Session, package_id, per_carton: bool = False) -> tuple[bytes, str]:
    from ..core import pdf

    package = _get_or_404(PackageDao(db), package_id)
    box = {
        "qr": package.boxId,
        "title": package.boxId,
        "subtitle": "KONTENA" if (package.packageType or "").upper() == "SEA" else "BOX",
        "lines": [f"Track: {package.trackNumber or '-'}", f"Mizigo: {len(split_ids(package.productList))}",
                  f"Kilo: {package.weight or 0:,.1f}"],
        "badge": "MELI" if (package.packageType or "").upper() == "SEA" else "NDEGE",
        "footer": config.COMPANY_NAME,
    }
    items = [box] + _expand(products_in(db, package_id), package.boxId, package.packageType, per_carton)
    return pdf.labels(items), f"lebo_{package.boxId}"


def invoice_labels_pdf(db: Session, invoice_id, per_carton: bool = False) -> tuple[bytes, str]:
    """Lebo za mizigo ya ankara moja (mf. wakati wa kupokea mzigo China, kabla ya kupakia)."""
    from ..core import pdf

    invoice = InvoiceDao(db).with_details(invoice_id)
    if invoice is None:
        raise NotFound("The Invoice does not exist")
    rows = [_product_row(p, invoice) for p in invoice.product]
    return pdf.labels(_expand(rows, None, None, per_carton)), f"lebo_ankara_{invoice.invoiceNumber}"
