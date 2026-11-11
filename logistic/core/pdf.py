"""
PDF zinazotengenezwa moja kwa moja kwa reportlab (haraka, hazihitaji LibreOffice):
risiti za malipo, hati ya makabidhiano, manifest ya box na lebo za QR.
"""
from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .. import config
from . import brand
from .utils import to_local, whole

BRAND = colors.HexColor("#1F4FD8")
INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#64748B")
LINE = colors.HexColor("#E2E8F0")
SOFT = colors.HexColor("#F1F5F9")


def _fmt_dt(value: datetime | None) -> str:
    return f"{to_local(value):%d/%m/%Y %H:%M}" if value else "-"


def _canvas(buf, pagesize) -> canvas.Canvas:
    """Canvas yenye jina la kampuni kwenye taarifa za PDF (author/creator)."""
    c = canvas.Canvas(buf, pagesize=pagesize)
    c.setAuthor(config.COMPANY_NAME)
    c.setCreator(config.COMPANY_NAME)
    c.setTitle(config.COMPANY_NAME)
    return c


def _header(c: canvas.Canvas, width: float, height: float, title: str, number: str) -> float:
    """Kichwa cha kampuni (logo + jina + simu); inarudisha y ya kuanzia maudhui."""
    m = 14 * mm
    accent = brand.color()
    c.setFillColor(accent)
    c.rect(0, height - 4 * mm, width, 4 * mm, stroke=0, fill=1)
    used = brand.draw_logo(c, m, height - 26.5 * mm, 26 * mm, 16 * mm)
    x = m + (used + 4 * mm if used else 0)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(x, height - 16 * mm, config.COMPANY_NAME)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    c.drawString(x, height - 21 * mm, f"Simu: {config.COMPANY_PHONES}")
    c.drawString(x, height - 25 * mm, f"Kutoka: {config.COMPANY_ORIGIN}")
    c.setFillColor(accent)
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(width - m, height - 16 * mm, title.upper())
    c.setFillColor(INK)
    c.setFont("Helvetica", 9)
    c.drawRightString(width - m, height - 21 * mm, f"No. {number}")
    c.drawRightString(width - m, height - 25 * mm, f"Tarehe: {datetime.now():%d/%m/%Y %H:%M}")
    c.setStrokeColor(LINE)
    c.line(m, height - 29 * mm, width - m, height - 29 * mm)
    return height - 37 * mm


def _rows(c: canvas.Canvas, x: float, y: float, w: float, rows: list[tuple[str, str]], gap: float = 6 * mm,
          bold_last: bool = False) -> float:
    for i, (label, value) in enumerate(rows):
        last = bold_last and i == len(rows) - 1
        c.setFont("Helvetica", 9)
        c.setFillColor(MUTED)
        c.drawString(x, y, label)
        c.setFont("Helvetica-Bold" if last else "Helvetica", 10.5 if last else 9.5)
        c.setFillColor(INK)
        c.drawRightString(x + w, y, value)
        y -= gap
    return y


def _footer(c: canvas.Canvas, width: float, text: str) -> None:
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillColor(MUTED)
    c.drawCentredString(width / 2, 8 * mm, text)


def _image(c: canvas.Canvas, path: Path, x: float, y: float, w: float, h: float) -> bool:
    """Picha (sahihi/picha ya mtu); faili likiwa bovu linarukwa badala ya kuvunja PDF."""
    try:
        c.drawImage(ImageReader(str(path)), x, y, w, h, preserveAspectRatio=True, mask="auto")
        return True
    except Exception:
        return False


def _qr(c: canvas.Canvas, value: str, x: float, y: float, size: float) -> None:
    widget = QrCodeWidget(value)
    b = widget.getBounds()
    w, h = b[2] - b[0], b[3] - b[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(widget)
    renderPDF.draw(d, c, x, y)


# ------------------------------------------------------------------ risiti
def receipt(payment, debt, invoice, institute, cashier) -> bytes:
    buf = BytesIO()
    width, height = A5
    c = _canvas(buf, pagesize=A5)
    refund = payment.kind == "REFUND"
    y = _header(c, width, height, "Risiti ya kurudisha" if refund else "Risiti ya malipo",
                payment.receiptNumber or str(payment.id)[:8])
    m = 14 * mm
    w = width - 2 * m
    customer = invoice.customer[0] if invoice and invoice.customer else None

    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(INK)
    c.drawString(m, y, "Mteja")
    y -= 5.5 * mm
    y = _rows(c, m, y, w, [
        ("Jina", customer.name if customer else "-"),
        ("Simu", (customer.phoneNumber if customer else None) or "-"),
        ("Ankara", invoice.invoiceNumber if invoice else "-"),
    ])
    y -= 2 * mm

    # kiasi kikubwa
    c.setFillColor(SOFT)
    c.roundRect(m, y - 16 * mm, w, 18 * mm, 3 * mm, stroke=0, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(m + 5 * mm, y - 4 * mm, "Kiasi kilichorudishwa" if refund else "Kiasi kilicholipwa")
    c.setFillColor(colors.HexColor("#B91C1C") if refund else BRAND)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(m + 5 * mm, y - 12 * mm, f"TSh {whole(payment.paid)}")
    if payment.amountOriginal and payment.currency not in ("TZS", "TSH", "TSHS"):
        c.setFont("Helvetica", 8.5)
        c.setFillColor(MUTED)
        c.drawRightString(m + w - 5 * mm, y - 12 * mm,
                          f"{payment.currency} {payment.amountOriginal:,.2f} @ {whole(payment.rate)}")
    y -= 24 * mm

    rows = [
        ("Njia ya malipo", f"{institute.name} ({institute.accountNo})" if institute else "-"),
        ("Muda", _fmt_dt(payment.created_at)),
        ("Aliyepokea", f"{cashier.firstName} {cashier.lastName}" if cashier else "-"),
    ]
    if payment.note:
        rows.append(("Maelezo", payment.note[:60]))
    y = _rows(c, m, y, w, rows)
    y -= 2 * mm
    c.setStrokeColor(LINE)
    c.line(m, y + 3 * mm, m + w, y + 3 * mm)
    y -= 2 * mm

    if debt is not None:
        summary = [("Usafirishaji", f"TSh {whole(debt.amount)}")]
        if debt.storageCharge:
            summary.append((f"Gharama za stoo ({debt.days} siku)", f"TSh {whole(debt.storageCharge)}"))
        if debt.discount:
            summary.append(("Punguzo", f"- TSh {whole(debt.discount)}"))
        summary += [("Jumla ya kulipwa", f"TSh {whole(debt.paid)}"),
                    ("Kilichobaki", f"TSh {whole(max(debt.debt or 0, 0))}")]
        y = _rows(c, m, y, w, summary, bold_last=True)

    if payment.receiptNumber:
        _qr(c, f"{config.COMPANY_NAME}|{payment.receiptNumber}|{whole(payment.paid)}", width - m - 22 * mm,
            14 * mm, 22 * mm)
    _footer(c, width, "Ahsante kwa kuchagua huduma zetu. Risiti hii imetolewa na mfumo.")
    c.showPage()
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------- makabidhiano
def handover_note(handover, invoice, debt, staff, signature: Path | None, photo: Path | None) -> bytes:
    buf = BytesIO()
    width, height = A4
    c = _canvas(buf, pagesize=A4)
    y = _header(c, width, height, "Hati ya makabidhiano", invoice.invoiceNumber)
    m = 14 * mm
    w = width - 2 * m
    customer = invoice.customer[0] if invoice.customer else None

    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(INK)
    c.drawString(m, y, "Mzigo")
    y -= 6 * mm
    products = list(invoice.product or [])
    items = {i.product_id: i.cartons for i in (getattr(handover, "items", None) or [])}
    partial = bool(items)
    if partial:  # makabidhiano ya sehemu: mizigo na katoni zilizochukuliwa sasa tu
        products = [p for p in products if p.id in items]
    c.setFillColor(SOFT)
    c.rect(m, y - 2 * mm, w, 7 * mm, stroke=0, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(m + 2 * mm, y, "#")
    c.drawString(m + 10 * mm, y, "MAELEZO")
    c.drawString(m + 95 * mm, y, "TRACK NO.")
    c.drawRightString(m + w - 30 * mm, y, "IDADI")
    c.drawRightString(m + w - 2 * mm, y, "KILO")
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    c.setFillColor(INK)
    for i, p in enumerate(products[:22], start=1):
        c.drawString(m + 2 * mm, y, str(i))
        c.drawString(m + 10 * mm, y, (p.description or "")[:48])
        c.drawString(m + 95 * mm, y, (p.trackNumber or "-")[:24])
        c.drawRightString(m + w - 30 * mm, y, f"{items.get(p.id, p.quantities):,.0f}"
                          + (f"/{p.quantities:,.0f}" if partial and items.get(p.id) != p.quantities else ""))
        c.drawRightString(m + w - 2 * mm, y, f"{p.weight:,.1f}")
        y -= 5.5 * mm
    if len(products) > 22:
        c.drawString(m + 10 * mm, y, f"... na mingine {len(products) - 22}")
        y -= 5.5 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(m + w - 2 * mm, y, f"Jumla: {sum(p.weight or 0 for p in products):,.1f} kg")
    y -= 10 * mm

    if partial:
        c.setFont("Helvetica-Oblique", 8.5)
        c.setFillColor(MUTED)
        c.drawString(m, y + 4 * mm, "Makabidhiano ya sehemu: katoni zilizochukuliwa sasa / jumla ya katoni")
        c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(m, y, "Aliyechukua")
    y -= 6 * mm
    half = w / 2 - 6 * mm
    rows = [
        ("Jina", handover.collectorName),
        ("Simu", handover.collectorPhone or "-"),
        ("Kitambulisho", f"{handover.idType or '-'} {handover.idNumber or ''}".strip()),
        ("Mwenye ankara", customer.name if customer else "-"),
        ("Muda", _fmt_dt(handover.created_at)),
        ("Aliyekabidhi", f"{staff.firstName} {staff.lastName}" if staff else "-"),
    ]
    if not handover.isReceiver:
        rows.append(("Hali", "Amechukua kwa niaba"))
    if handover.onCredit:
        rows.append(("Deni wakati wa kukabidhi", f"TSh {whole(handover.balance)}"))
    if handover.note:
        rows.append(("Maelezo", handover.note[:50]))
    y_after = _rows(c, m, y, half, rows)

    # sahihi na picha upande wa kulia
    box_x = m + half + 12 * mm
    box_w = w - half - 12 * mm
    top = y + 4 * mm
    if signature and signature.exists():
        c.setStrokeColor(LINE)
        c.rect(box_x, top - 32 * mm, box_w, 32 * mm, stroke=1, fill=0)
        _image(c, signature, box_x + 2 * mm, top - 30 * mm, box_w - 4 * mm, 28 * mm)
        c.setFont("Helvetica", 8)
        c.setFillColor(MUTED)
        c.drawString(box_x, top - 36 * mm, "Sahihi ya aliyechukua")
        top -= 42 * mm
    if photo and photo.exists():
        _image(c, photo, box_x, top - 45 * mm, box_w, 45 * mm)
        top -= 50 * mm
    y = min(y_after, top) - 6 * mm

    if debt is not None:
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(INK)
        c.drawString(m, y, "Malipo")
        y -= 6 * mm
        _rows(c, m, y, half, [("Jumla", f"TSh {whole((debt.amount or 0) + (debt.storageCharge or 0) - (debt.discount or 0))}"),
                               ("Imelipwa", f"TSh {whole(debt.paid)}"),
                               ("Baki", f"TSh {whole(max(debt.debt or 0, 0))}")], bold_last=True)

    _footer(c, width, "Aliyechukua amethibitisha kupokea mzigo ulioorodheshwa hapo juu ukiwa katika hali nzuri.")
    c.showPage()
    c.save()
    return buf.getvalue()


# ------------------------------------------------------------------ manifest
def manifest(package, rows: list[dict]) -> bytes:
    """
    Orodha ya kila mzigo ndani ya box/kontena (A4 mlalo).
    rows: dict zenye invoiceNumber, customerName, customerPhone, receiverName, receiverPhone,
          description, trackNumber, quantities, weight, cbm
    """
    from reportlab.lib.pagesizes import landscape

    buf = BytesIO()
    width, height = landscape(A4)
    c = _canvas(buf, pagesize=(width, height))
    m = 12 * mm
    kind = "Kontena (Meli)" if (package.packageType or "").upper() == "SEA" else "Box (Ndege)"
    state = "Limefika stoo" if package.isCollect else ("Safarini" if package.isBoxClose else "Linapakiwa")

    cols = [  # (kichwa, upana mm, mpangilio)
        ("#", 8, "l"), ("ANKARA", 20, "l"), ("MTEJA", 38, "l"), ("MPOKEAJI", 38, "l"), ("MAELEZO", 48, "l"),
        ("TRACK NO.", 38, "l"), ("KATONI", 16, "r"), ("KILO", 18, "r"), ("CBM", 16, "r"), ("OK", 10, "c"),
    ]

    def header() -> float:
        y = _header(c, width, height, f"Manifest - {kind}", package.boxId)
        c.setFont("Helvetica", 9)
        c.setFillColor(INK)
        info = f"Track ya usafirishaji: {package.trackNumber or '-'}    Hali: {state}    " \
               f"Tarehe ya kuundwa: {_fmt_dt(package.created_at)}"
        c.drawString(m, y + 3 * mm, info)
        _qr(c, package.boxId, width - m - 16 * mm, y - 15 * mm, 16 * mm)
        y -= 6 * mm
        c.setFillColor(SOFT)
        c.rect(m, y - 2 * mm, width - 2 * m - 22 * mm, 7 * mm, stroke=0, fill=1)
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Bold", 7.5)
        x = m + 2 * mm
        for title, w, align in cols:
            if align == "r":
                c.drawRightString(x + w * mm - 2 * mm, y, title)
            elif align == "c":
                c.drawCentredString(x + w * mm / 2, y, title)
            else:
                c.drawString(x, y, title)
            x += w * mm
        return y - 7 * mm

    y = header()
    page = 1
    for i, r in enumerate(rows, start=1):
        if y < 22 * mm:
            _footer(c, width, f"Ukurasa {page}")
            c.showPage()
            page += 1
            y = header()
        c.setFont("Helvetica", 8)
        c.setFillColor(INK)
        values = [
            str(i), r.get("invoiceNumber") or "-",
            f"{(r.get('customerName') or '-')[:20]}", f"{(r.get('receiverName') or '-')[:20]}",
            (r.get("description") or "")[:30], (r.get("trackNumber") or "-")[:22],
            f"{r.get('quantities') or 0:,.0f}", f"{r.get('weight') or 0:,.1f}", f"{r.get('cbm') or 0:,.3f}", "",
        ]
        x = m + 2 * mm
        for (title, w, align), v in zip(cols, values):
            if align == "r":
                c.drawRightString(x + w * mm - 2 * mm, y, v)
            elif align == "c":
                c.rect(x + w * mm / 2 - 1.6 * mm, y - 0.6 * mm, 3.2 * mm, 3.2 * mm, stroke=1, fill=0)
            else:
                c.drawString(x, y, v)
            x += w * mm
        # simu chini ya majina
        c.setFont("Helvetica", 6.5)
        c.setFillColor(MUTED)
        c.drawString(m + 2 * mm + 28 * mm, y - 3 * mm, (r.get("customerPhone") or "")[:20])
        c.drawString(m + 2 * mm + 66 * mm, y - 3 * mm, (r.get("receiverPhone") or "")[:20])
        c.setStrokeColor(LINE)
        c.line(m, y - 5 * mm, width - m - 22 * mm, y - 5 * mm)
        y -= 9 * mm

    # jumla na sahihi
    if y < 40 * mm:
        _footer(c, width, f"Ukurasa {page}")
        c.showPage()
        page += 1
        y = height - 25 * mm
    customers = len({r.get("invoiceNumber") for r in rows})
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(INK)
    c.drawString(m, y - 2 * mm, f"Jumla: mizigo {len(rows)} · ankara {customers} · katoni "
                                 f"{sum(r.get('quantities') or 0 for r in rows):,.0f} · kilo "
                                 f"{sum(r.get('weight') or 0 for r in rows):,.1f} · CBM "
                                 f"{sum(r.get('cbm') or 0 for r in rows):,.3f}")
    y -= 18 * mm
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    for k, label in enumerate(("Aliyepakia (jina na sahihi)", "Aliyekagua", "Aliyepokea stoo")):
        x = m + k * (width - 2 * m) / 3
        c.line(x, y, x + 70 * mm, y)
        c.drawString(x, y - 4 * mm, label)
    _footer(c, width, f"Ukurasa {page} · {config.COMPANY_NAME}")
    c.showPage()
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------- lebo
LABEL_SIZE = (100 * mm, 70 * mm)  # printa ya lebo (thermal) - pia inachapishika kwenye A4 ukipenda


def labels(items: list[dict]) -> bytes:
    """
    Lebo moja kwa kila item: {"qr", "title", "subtitle", "lines": [..], "badge", "footer"}.
    """
    buf = BytesIO()
    w, h = LABEL_SIZE
    c = _canvas(buf, pagesize=LABEL_SIZE)
    for item in items or [{"qr": "-", "title": "-", "lines": []}]:
        c.setStrokeColor(INK)
        c.setLineWidth(1.2)
        c.roundRect(2.5 * mm, 2.5 * mm, w - 5 * mm, h - 5 * mm, 3 * mm, stroke=1, fill=0)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 9)
        used = brand.draw_logo(c, 6 * mm, h - 10.5 * mm, 12 * mm, 6 * mm)
        c.drawString(6 * mm + (used + 1.5 * mm if used else 0), h - 9 * mm, config.COMPANY_NAME)
        if item.get("badge"):
            c.setFillColor(INK)
            badge = str(item["badge"])
            bw = c.stringWidth(badge, "Helvetica-Bold", 9) + 5 * mm
            c.roundRect(w - 6 * mm - bw, h - 11 * mm, bw, 6 * mm, 1.5 * mm, stroke=0, fill=1)
            c.setFillColor(colors.white)
            c.drawCentredString(w - 6 * mm - bw / 2, h - 9 * mm, badge)
        c.setFillColor(INK)
        qr_size = 34 * mm
        _qr(c, str(item.get("qr") or "-"), 5 * mm, h - 14 * mm - qr_size, qr_size)
        x = 42 * mm
        y = h - 19 * mm
        c.setFont("Helvetica-Bold", 14)
        c.drawString(x, y, str(item.get("title") or "")[:18])
        y -= 6 * mm
        if item.get("subtitle"):
            c.setFont("Helvetica-Bold", 9.5)
            c.drawString(x, y, str(item["subtitle"])[:28])
            y -= 5.5 * mm
        c.setFont("Helvetica", 8.5)
        for line in item.get("lines", [])[:6]:
            c.drawString(x, y, str(line)[:32])
            y -= 4.6 * mm
        if item.get("code"):  # code ya ofisi: kubwa, chini ya QR (mpokeaji anaionyesha kuchukua mzigo)
            code = str(item["code"])[:20]
            c.setFont("Helvetica-Bold", 7)
            c.drawString(5 * mm, 16 * mm, "CODE YA OFISI")
            size = 15 if len(code) <= 8 else 11
            c.setFont("Helvetica-Bold", size)
            c.roundRect(4 * mm, 9.5 * mm, 36 * mm, 6 * mm, 1.2 * mm, stroke=1, fill=0)
            c.drawCentredString(22 * mm, 11 * mm, code)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(MUTED)
        c.drawString(6 * mm, 6 * mm, str(item.get("footer") or "")[:70])
        c.showPage()
    c.save()
    return buf.getvalue()


# ------------------------------------------------------------------- ankara
def invoice(inv, customer, rows: list[dict], extra_rows: list[tuple[str, float]], receiver=None,
            track_url: str | None = None) -> bytes:
    """
    Ankara (A4). rows: {description, track, carrier, quantities, weight, cbm, amount}
    extra_rows: [(maelezo, kiasi)] mf. gharama za stoo (+) na punguzo (-).
    """
    buf = BytesIO()
    width, height = A4
    c = _canvas(buf, pagesize=A4)
    m = 14 * mm
    w = width - 2 * m

    def head() -> float:
        y = _header(c, width, height, "Ankara / Invoice", inv.invoiceNumber)
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(INK)
        c.drawString(m, y, "Mteja")
        if receiver is not None:
            c.drawString(m + w / 2, y, "Mpokeaji")
        c.setFont("Helvetica", 9.5)
        c.drawString(m, y - 5 * mm, customer.name if customer else "-")
        c.setFillColor(MUTED)
        c.drawString(m, y - 10 * mm, (customer.phoneNumber if customer else None) or "")
        if receiver is not None:
            c.setFillColor(INK)
            c.drawString(m + w / 2, y - 5 * mm, receiver.name)
            c.setFillColor(MUTED)
            c.drawString(m + w / 2, y - 10 * mm, f"{receiver.phoneNumber or '-'} · Pickup: {receiver.trackNumber}")
        return y - 18 * mm

    cols = [("#", 8, "l"), ("MAELEZO", 62, "l"), ("TRACK NO.", 36, "l"), ("KATONI", 16, "r"),
            ("KILO", 18, "r"), ("CBM", 16, "r"), ("KIASI (TSh)", 26, "r")]

    def table_head(y: float) -> float:
        c.setFillColor(SOFT)
        c.rect(m, y - 2 * mm, w, 7 * mm, stroke=0, fill=1)
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Bold", 8)
        x = m + 2 * mm
        for title, cw, align in cols:
            (c.drawRightString(x + cw * mm - 2 * mm, y, title) if align == "r" else c.drawString(x, y, title))
            x += cw * mm
        return y - 8 * mm

    y = table_head(head())
    total = 0.0
    for i, r in enumerate(rows, start=1):
        if y < 60 * mm:
            _footer(c, width, f"Inaendelea... · {config.COMPANY_NAME}")
            c.showPage()
            y = table_head(head())
        total += r.get("amount") or 0
        values = [str(i), (r.get("description") or "")[:40], (r.get("track") or "-")[:22],
                  f"{r.get('quantities') or 0:,.0f}", f"{r.get('weight') or 0:,.1f}",
                  f"{r['cbm']:,.3f}" if r.get("cbm") else "-", whole(r.get("amount"))]
        x = m + 2 * mm
        c.setFont("Helvetica", 8.8)
        c.setFillColor(INK)
        for (title, cw, align), v in zip(cols, values):
            (c.drawRightString(x + cw * mm - 2 * mm, y, v) if align == "r" else c.drawString(x, y, v))
            x += cw * mm
        c.setFont("Helvetica", 6.8)
        c.setFillColor(MUTED)
        c.drawString(m + 10 * mm, y - 3.2 * mm, "Meli" if (r.get("carrier") or "").upper() == "SEA" else "Ndege")
        c.setStrokeColor(LINE)
        c.line(m, y - 5 * mm, m + w, y - 5 * mm)
        y -= 9 * mm

    # jumla
    y -= 2 * mm
    right = m + w
    lines = [("Jumla ya usafirishaji", total)] + list(extra_rows)
    grand = total + sum(v for _, v in extra_rows)
    for label, value in lines:
        c.setFont("Helvetica", 9.5)
        c.setFillColor(MUTED)
        c.drawRightString(right - 34 * mm, y, label)
        c.setFillColor(INK)
        c.drawRightString(right - 2 * mm, y, ("- " if value < 0 else "") + whole(abs(value)))
        y -= 5.5 * mm
    y -= 4 * mm
    c.setFillColor(BRAND)
    c.roundRect(right - 80 * mm, y - 4 * mm, 80 * mm, 10 * mm, 2 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(right - 77 * mm, y - 0.5 * mm, "JUMLA YA KULIPA")
    c.drawRightString(right - 3 * mm, y - 0.5 * mm, f"TSh {whole(grand)}")
    y -= 16 * mm

    # maelezo ya malipo + QR
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(m, y, "Lipa kupitia")
    c.setFont("Helvetica", 8.8)
    yy = y - 5 * mm
    for line in (config.COMPANY_PAYMENT_INFO or "").splitlines():
        c.drawString(m, yy, line[:60])
        yy -= 4.3 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(MUTED)
    c.drawString(m, yy - 2 * mm, f"Taja namba ya ankara {inv.invoiceNumber} unapolipa. Mzigo unakaa stoo siku "
                                 f"{config.DAYS_TO_CHARGE} bure, kisha ${config.STORAGE_CHARGE_USD:,.2f} kwa siku.")
    code = (receiver.trackNumber if receiver is not None else None) or inv.invoiceNumber
    qr_value = f"{track_url}{'&' if '?' in track_url else '?'}code={code}" if track_url else code
    _qr(c, qr_value, right - 26 * mm, y - 26 * mm, 26 * mm)
    c.setFont("Helvetica", 7)
    c.setFillColor(MUTED)
    c.drawCentredString(right - 13 * mm, y - 29 * mm, "Fuatilia mzigo")

    _footer(c, width, f"Ahsante kwa kuchagua {config.COMPANY_NAME}. Ankara hii imetolewa na mfumo.")
    c.showPage()
    c.save()
    return buf.getvalue()
