"""
Risiti ya malipo ya subscription (kutoka kwako - PLATFORM_NAME - kwenda kwa kampuni).
Inatengenezwa kwa malipo yaliyothibitishwa (CONFIRMED) tu.
"""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from ... import config
from ...core.utils import to_local

BRAND = colors.HexColor("#1F4FD8")
INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#64748B")
LINE = colors.HexColor("#E2E8F0")
SOFT = colors.HexColor("#F1F5F9")
GOOD = colors.HexColor("#15803D")


def number(payment) -> str:
    """Namba ya risiti: SUB-YYYYMM-XXXXXX (sehemu ya id - haibadiliki)."""
    when = payment.reviewedAt or payment.created_at
    return f"SUB-{when:%Y%m}-{str(payment.id).replace('-', '')[:6].upper()}"


def _money(currency: str, amount: float) -> str:
    return f"{currency} {amount:,.0f}" if float(amount).is_integer() else f"{currency} {amount:,.2f}"


def _d(value) -> str:
    return f"{to_local(value):%d/%m/%Y}" if value else "-"


def pdf(payment, company, subscription=None) -> bytes:
    buffer = BytesIO()
    width, height = A5
    c = canvas.Canvas(buffer, pagesize=A5)
    c.setTitle(f"Risiti {number(payment)}")
    m = 12 * mm

    # kichwa: wewe (mtoa huduma)
    c.setFillColor(BRAND)
    c.rect(0, height - 4 * mm, width, 4 * mm, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(m, height - 15 * mm, config.PLATFORM_NAME)
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    y = height - 20 * mm
    for line in (config.PLATFORM_SUPPORT_PHONE, config.PLATFORM_SUPPORT_EMAIL, config.PLATFORM_DOMAIN):
        if line:
            c.drawString(m, y, line)
            y -= 3.8 * mm
    c.setFillColor(BRAND)
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(width - m, height - 15 * mm, "RISITI / RECEIPT")
    c.setFillColor(INK)
    c.setFont("Helvetica", 8.5)
    c.drawRightString(width - m, height - 20 * mm, f"No. {number(payment)}")
    c.drawRightString(width - m, height - 24 * mm, f"Tarehe: {_d(payment.reviewedAt or payment.created_at)}")
    top = min(y, height - 28 * mm) - 2 * mm
    c.setStrokeColor(LINE)
    c.line(m, top, width - m, top)

    # mteja (kampuni)
    y = top - 7 * mm
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawString(m, y, "IMEPOKELEWA KUTOKA / RECEIVED FROM")
    y -= 5 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(m, y, (company.legalName or company.name)[:60])
    c.setFont("Helvetica", 8.5)
    for line in (f"Code: {company.slug}", f"TIN: {company.tin}" if company.tin else None,
                 company.phone or company.ownerPhone, company.email, company.address):
        if line:
            y -= 4.2 * mm
            c.drawString(m, y, str(line)[:80])

    # maelezo ya malipo
    y -= 8 * mm
    plan = getattr(payment, "plan", None)
    months = int(getattr(plan, "months", 1) or 1) * int(payment.periods or 1)
    rows = [
        ("Huduma / Service", f"Subscription - {plan.name if plan else '-'}"),
        ("Muda / Duration", f"Miezi {months} / {months} month(s)"),
    ]
    if subscription is not None:
        rows.append(("Kipindi / Period", f"{_d(subscription.startsAt)} - {_d(subscription.endsAt)}"))
    rows += [
        ("Njia / Method", payment.method or "-"),
        ("Kumbukumbu / Reference", payment.reference or "-"),
        ("Imethibitishwa na / Confirmed by", payment.reviewedBy or "-"),
    ]
    c.setFillColor(SOFT)
    box_h = (len(rows) * 6.5 + 4) * mm
    c.roundRect(m, y - box_h + 4 * mm, width - 2 * m, box_h, 2 * mm, stroke=0, fill=1)
    for label, value in rows:
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(m + 4 * mm, y, label)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawRightString(width - m - 4 * mm, y, str(value)[:55])
        y -= 6.5 * mm

    # jumla
    y -= 6 * mm
    c.setStrokeColor(LINE)
    c.line(m, y + 4 * mm, width - m, y + 4 * mm)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(m, y - 2 * mm, "JUMLA / TOTAL")
    c.setFillColor(BRAND)
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(width - m, y - 2 * mm, _money(payment.currency or "TZS", float(payment.amount or 0)))

    # muhuri wa "IMELIPWA"
    y -= 18 * mm
    c.saveState()
    c.translate(width / 2, y)
    c.rotate(8)
    c.setStrokeColor(GOOD)
    c.setFillColor(GOOD)
    c.setLineWidth(1.5)
    c.roundRect(-24 * mm, -6 * mm, 48 * mm, 12 * mm, 2 * mm, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(0, -2 * mm, "IMELIPWA / PAID")
    c.restoreState()

    c.setFont("Helvetica", 7)
    c.setFillColor(MUTED)
    c.drawCentredString(width / 2, 10 * mm, f"Ahsante kwa kutumia {config.PLATFORM_NAME} / Thank you for your business")
    c.showPage()
    c.save()
    return buffer.getvalue()
