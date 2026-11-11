"""
Mjenzi wa ripoti za PDF (reportlab platypus) - kichwa cha kampuni, kadi za takwimu, jedwali zenye jumla,
chati za pie na bar, namba za kurasa. Haihitaji Word wala LibreOffice.

    rep = ReportPdf("Muhtasari wa biashara", "01/10/2026 - 14/10/2026")
    rep.kpis([("Mapato", "TSh 1,200,000"), ...])
    rep.table(["Mwezi", "Kiasi"], rows, widths=[2, 1], money={1}, totals={1})
    rep.pie("Mapato kwa njia", [("CRDB", 1000), ("M-Pesa", 500)])
    pdf_bytes = rep.build()
"""
from datetime import datetime
from io import BytesIO

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (CondPageBreak, Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .. import config
from . import brand

BRAND = colors.HexColor("#1F4FD8")
INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#64748B")
LINE = colors.HexColor("#E2E8F0")
SOFT = colors.HexColor("#F1F5F9")
ZEBRA = colors.HexColor("#F8FAFC")
PALETTE = [colors.HexColor(c) for c in ("#1F4FD8", "#16A34A", "#F59E0B", "#DC2626", "#7C3AED", "#0891B2",
                                         "#DB2777", "#65A30D", "#EA580C", "#475569")]

_body = ParagraphStyle("rb", fontName="Helvetica", fontSize=8.6, leading=11, textColor=INK)
_cell = ParagraphStyle("rc", parent=_body, fontSize=8, leading=10)
_cell_r = ParagraphStyle("rcr", parent=_cell, alignment=2)
_head = ParagraphStyle("rh", parent=_cell, fontName="Helvetica-Bold", textColor=colors.white)
_head_r = ParagraphStyle("rhr", parent=_head, alignment=2)
_h2 = ParagraphStyle("rh2", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=BRAND, spaceBefore=8,
                     spaceAfter=5)
_note = ParagraphStyle("rn", parent=_body, fontSize=7.8, textColor=MUTED)


def money(v) -> str:
    try:
        return f"{float(v or 0):,.0f}"
    except (TypeError, ValueError):
        return str(v)


def num(v, digits: int = 2) -> str:
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:,.0f}" if f == int(f) else f"{f:,.{digits}f}"


def _esc(v) -> str:
    s = "" if v is None else str(v)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class _Kpis(Flowable):
    """Kadi za takwimu (lebo + thamani) kwenye mstari mmoja au zaidi."""

    def __init__(self, items: list[tuple[str, str]], width: float, per_row: int = 4):
        super().__init__()
        self.items, self.width, self.per_row = items, width, max(1, min(per_row, len(items) or 1))
        self.rows = (len(items) + self.per_row - 1) // self.per_row
        self.box_h = 15 * mm
        self.height = self.rows * (self.box_h + 3 * mm)

    def draw(self):
        c = self.canv
        gap = 3 * mm
        bw = (self.width - gap * (self.per_row - 1)) / self.per_row
        for i, (label, value) in enumerate(self.items):
            r, k = divmod(i, self.per_row)
            x = k * (bw + gap)
            y = self.height - (r + 1) * (self.box_h + gap) + gap
            c.setFillColor(SOFT)
            c.setStrokeColor(LINE)
            c.roundRect(x, y, bw, self.box_h, 2 * mm, fill=1, stroke=1)
            c.setFillColor(PALETTE[i % len(PALETTE)])
            c.rect(x, y + 2 * mm, 1.2 * mm, self.box_h - 4 * mm, fill=1, stroke=0)
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 7.3)
            c.drawString(x + 4 * mm, y + self.box_h - 5.2 * mm, str(label)[:48])
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 11)
            c.drawString(x + 4 * mm, y + 3.6 * mm, str(value)[:30])


class ReportPdf:
    def __init__(self, title: str, period: str | None = None, wide: bool = False, subtitle: str | None = None):
        self.title, self.period, self.subtitle = title, period, subtitle
        self.pagesize = landscape(A4) if wide else A4
        self.margin = 13 * mm
        self.width = self.pagesize[0] - 2 * self.margin
        self.story: list = []

    # ------------------------------------------------------------ vipande
    def kpis(self, items: list[tuple[str, str]], per_row: int = 4):
        if items:
            self.story += [_Kpis(items, self.width, per_row), Spacer(1, 3 * mm)]

    def section(self, title: str):
        self.story += [CondPageBreak(30 * mm), Paragraph(_esc(title), _h2)]

    def note(self, text: str):
        self.story += [Paragraph(_esc(text), _note), Spacer(1, 2 * mm)]

    def table(self, headers: list[str], rows: list[list], widths: list[float] | None = None,
              money: set[int] | None = None, numbers: set[int] | None = None, totals: set[int] | None = None,
              total_label: str = "JUMLA", empty: str = "Hakuna data kwa kipindi hiki."):
        money, numbers, totals = money or set(), numbers or set(), totals or set()
        right = money | numbers
        if not rows:
            self.story += [Paragraph(_esc(empty), _note), Spacer(1, 3 * mm)]
            return

        def fmt(i, v):
            if i in money:
                return globals()["money"](v)
            if i in numbers:
                return num(v)
            return v

        data = [[Paragraph(_esc(h), _head_r if i in right else _head) for i, h in enumerate(headers)]]
        for r in rows:
            data.append([Paragraph(_esc(fmt(i, v)), _cell_r if i in right else _cell) for i, v in enumerate(r)])
        if totals:
            t = []
            for i in range(len(headers)):
                if i in totals:
                    s = sum(float(r[i] or 0) for r in rows if isinstance(r[i], (int, float)))
                    t.append(Paragraph(f"<b>{_esc(fmt(i, s))}</b>", _cell_r))
                else:
                    t.append(Paragraph(f"<b>{_esc(total_label)}</b>" if i == 0 else "", _cell))
            data.append(t)
        w = widths or [1] * len(headers)
        scale = self.width / sum(w)
        tbl = Table(data, colWidths=[x * scale for x in w], repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1 if not totals else -2), [colors.white, ZEBRA]),
        ]
        if totals:
            style += [("BACKGROUND", (0, -1), (-1, -1), SOFT), ("LINEABOVE", (0, -1), (-1, -1), 0.8, INK)]
        tbl.setStyle(TableStyle(style))
        self.story += [tbl, Spacer(1, 4 * mm)]

    def pie(self, title: str, items: list[tuple[str, float]], value_fmt=money):
        items = [(str(k), float(v or 0)) for k, v in items if (v or 0) > 0]
        if not items:
            return
        total = sum(v for _, v in items)
        h = max(46 * mm, (len(items) * 5.5 + 12) * mm)
        d = Drawing(self.width, h)
        d.add(String(0, h - 5 * mm, title, fontName="Helvetica-Bold", fontSize=9.5, fillColor=INK))
        pie = Pie()
        size = min(36 * mm, h - 10 * mm)
        pie.x, pie.y, pie.width, pie.height = 4 * mm, (h - 8 * mm - size) / 2, size, size
        pie.data = [v for _, v in items]
        pie.labels = None
        pie.innerRadiusFraction = 0.5
        pie.strokeColor = colors.white
        pie.strokeWidth = 1
        for i in range(len(items)):
            pie.slices[i].fillColor = PALETTE[i % len(PALETTE)]
        d.add(pie)
        lx = size + 14 * mm
        for i, (label, v) in enumerate(items):
            y = h - 13 * mm - i * 5.5 * mm
            d.add(Rect(lx, y, 3 * mm, 3 * mm, fillColor=PALETTE[i % len(PALETTE)], strokeColor=None))
            d.add(String(lx + 5 * mm, y + 0.4 * mm, f"{label[:40]}", fontName="Helvetica", fontSize=8, fillColor=INK))
            d.add(String(lx + 80 * mm, y + 0.4 * mm, f"{value_fmt(v)}  ({v / total * 100:.1f}%)",
                         fontName="Helvetica-Bold", fontSize=8, fillColor=INK))
        self.story += [KeepTogether([d]), Spacer(1, 3 * mm)]

    def pies(self, charts: list[tuple[str, list[tuple[str, float]]]]):
        for title, items in charts:
            self.pie(title, items)

    def bars(self, title: str, labels: list[str], series: list[tuple[str, list[float]]]):
        if not labels or not any(any(v for v in s) for _, s in series):
            return
        h = 62 * mm
        d = Drawing(self.width, h)
        d.add(String(0, h - 5 * mm, title, fontName="Helvetica-Bold", fontSize=9.5, fillColor=INK))
        ch = VerticalBarChart()
        ch.x, ch.y, ch.width, ch.height = 16 * mm, 10 * mm, self.width - 20 * mm, h - 24 * mm
        ch.data = [[float(v or 0) for v in s] for _, s in series]
        ch.categoryAxis.categoryNames = [str(x) for x in labels]
        ch.categoryAxis.labels.fontSize = 6.5
        ch.categoryAxis.labels.angle = 30 if len(labels) > 8 else 0
        ch.categoryAxis.labels.dy = -2
        ch.valueAxis.labels.fontSize = 6.5
        ch.valueAxis.valueMin = 0
        ch.valueAxis.labelTextFormat = lambda v: f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.0f}K" if v >= 1e3 else f"{v:.0f}"
        ch.barSpacing = 1
        ch.groupSpacing = 4
        for i in range(len(series)):
            ch.bars[i].fillColor = PALETTE[i % len(PALETTE)]
            ch.bars[i].strokeColor = None
        d.add(ch)
        lx = 16 * mm
        for i, (name, _) in enumerate(series):
            d.add(Rect(lx, h - 11 * mm, 3 * mm, 3 * mm, fillColor=PALETTE[i % len(PALETTE)], strokeColor=None))
            d.add(String(lx + 4.5 * mm, h - 10.6 * mm, name, fontName="Helvetica", fontSize=7.5, fillColor=INK))
            lx += 8 * mm + len(name) * 1.6 * mm
        self.story += [KeepTogether([d]), Spacer(1, 3 * mm)]

    # ------------------------------------------------------------ kujenga
    def _page(self, c, doc):
        w, h = self.pagesize
        m = self.margin
        c.saveState()
        accent = brand.color()
        c.setFillColor(accent)
        c.rect(0, h - 3.5 * mm, w, 3.5 * mm, stroke=0, fill=1)
        used = brand.draw_logo(c, m, h - 18 * mm, 22 * mm, 12 * mm)
        x = m + (used + 3 * mm if used else 0)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(x, h - 12 * mm, config.COMPANY_NAME)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(MUTED)
        c.drawString(x, h - 16.5 * mm, f"Simu: {config.COMPANY_PHONES}")
        c.setFillColor(accent)
        c.setFont("Helvetica-Bold", 12)
        c.drawRightString(w - m, h - 12 * mm, self.title.upper())
        c.setFillColor(INK)
        c.setFont("Helvetica", 8)
        right = self.period or ""
        if self.subtitle:
            right = f"{self.subtitle}   {right}".strip()
        c.drawRightString(w - m, h - 16.5 * mm, right)
        c.setStrokeColor(LINE)
        c.line(m, h - 19.5 * mm, w - m, h - 19.5 * mm)
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        c.drawString(m, 7 * mm, f"Imetolewa: {datetime.now():%d/%m/%Y %H:%M}")
        c.drawRightString(w - m, 7 * mm, f"Ukurasa {doc.page}")
        c.restoreState()

    def build(self) -> bytes:
        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=self.pagesize, leftMargin=self.margin, rightMargin=self.margin,
                                topMargin=24 * mm, bottomMargin=13 * mm, title=self.title,
                                author=config.COMPANY_NAME)
        doc.build(self.story or [Paragraph("Hakuna data.", _note)], onFirstPage=self._page, onLaterPages=self._page)
        return buf.getvalue()
