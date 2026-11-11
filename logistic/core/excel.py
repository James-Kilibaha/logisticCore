"""Kutengeneza faili za Excel (.xlsx) kwa ripoti - kichwa chenye rangi, upana wa safu, namba na jumla."""
from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .. import config

_HEAD_FILL = PatternFill("solid", fgColor="1F4FD8")
_HEAD_FONT = Font(bold=True, color="FFFFFF")
_TOTAL_FONT = Font(bold=True)


class Sheet:
    def __init__(self, title: str, headers: list[str], rows: list[list], money: set[int] | None = None,
                 totals: set[int] | None = None, subtitle: str | None = None):
        self.title = title[:31]
        self.headers = headers
        self.rows = rows
        self.money = money or set()      # index za safu za pesa (format #,##0)
        self.totals = totals or set()    # index za safu za kujumlisha mwishoni
        self.subtitle = subtitle


def build(sheets: list[Sheet]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for sheet in sheets:
        ws = wb.create_sheet(sheet.title)
        ws.append([f"{config.COMPANY_NAME} - {sheet.title}"])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append([sheet.subtitle or f"Imetolewa {datetime.now():%d/%m/%Y %H:%M}"])
        ws["A2"].font = Font(italic=True, color="64748B")
        ws.append([])
        ws.append(sheet.headers)
        head_row = ws.max_row
        for col in range(1, len(sheet.headers) + 1):
            cell = ws.cell(row=head_row, column=col)
            cell.fill = _HEAD_FILL
            cell.font = _HEAD_FONT
            cell.alignment = Alignment(vertical="center")
        for row in sheet.rows:
            ws.append([v.replace(tzinfo=None) if isinstance(v, datetime) and v.tzinfo else v for v in row])
            r = ws.max_row
            for i, v in enumerate(row):
                cell = ws.cell(row=r, column=i + 1)
                if i in sheet.money:
                    cell.number_format = "#,##0"
                elif isinstance(v, datetime):
                    cell.number_format = "dd/mm/yyyy hh:mm"
                elif isinstance(v, date):
                    cell.number_format = "dd/mm/yyyy"
        if sheet.totals and sheet.rows:
            first, last = head_row + 1, ws.max_row
            total_row = [None] * len(sheet.headers)
            total_row[0] = "JUMLA"
            ws.append(total_row)
            r = ws.max_row
            for i in sheet.totals:
                letter = get_column_letter(i + 1)
                cell = ws.cell(row=r, column=i + 1, value=f"=SUM({letter}{first}:{letter}{last})")
                cell.number_format = "#,##0"
            for col in range(1, len(sheet.headers) + 1):
                ws.cell(row=r, column=col).font = _TOTAL_FONT
        ws.freeze_panes = ws.cell(row=head_row + 1, column=1)
        for i, header in enumerate(sheet.headers, start=1):
            width = max([len(str(header))] + [len(str(row[i - 1])) for row in sheet.rows[:300] if i - 1 < len(row)])
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 48)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
