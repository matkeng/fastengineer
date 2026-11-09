"""CSV / xlsx of the tags list, with a per-symbol detail sheet."""

from __future__ import annotations

import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .pipeline import SheetResult, tags_table

HEAD = Font(bold=True, color="FFFFFF")
FILL = PatternFill("solid", fgColor="305496")
DETAIL = ["Drawing", "Page", "Tag", "Source", "Template", "Score", "Variant", "Parts", "x1", "y1", "x2", "y2"]


def tags_csv(sheets: list[SheetResult], columns: list[str] | None = None) -> bytes:
    headers, rows = tags_table(sheets, columns)
    buf = io.StringIO()
    w = csv.DictWriter(buf, headers, lineterminator="\r\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def _sheet(ws, headers: list[str], rows: list[list]) -> None:
    ws.append(headers)
    for c in ws[1]:
        c.font, c.fill = HEAD, FILL
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, h in enumerate(headers, 1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:500]])
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 8), 60)


def tags_xlsx(sheets: list[SheetResult], title: str, columns: list[str] | None = None) -> bytes:
    headers, rows = tags_table(sheets, columns)
    wb = Workbook()
    ws = wb.active
    ws.title = "Tags"
    _sheet(ws, headers, [[int(r[h]) if h == "Count" else r[h] for h in headers] for r in rows])
    detail = []
    for sh in sheets:
        res = sh.result
        for s in res.symbols:
            parts = "; ".join(f"{k}={v if v is not None else 'Not found'}" for k, v in s.parts.items())
            detail.append([sh.file_name, res.page, s.tag or "", "template", s.template_desc, s.score, s.variant,
                           parts, *s.box])
        for t in res.tags:
            if t.source == "pattern":
                detail.append([sh.file_name, res.page, t.tag, "text scan", "", "", "", "", *t.box])
    _sheet(wb.create_sheet("Detections"), DETAIL, detail)
    info = wb.create_sheet("About")
    info.append([title])
    info.append(["Drawings", len({s.file_name for s in sheets})])
    info.append(["Sheets", len(sheets)])
    info.append(["Unique tags", len(rows)])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
