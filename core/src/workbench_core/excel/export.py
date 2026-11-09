"""Write a comparison to an .xlsx workbook.

Sheets:
  Differences   one row per key, coloured by status; changed cells as "old → new"
  Cell changes  one row per changed cell (key, column, change, old, new), easy to filter
  Summary       what was compared, counts, options and warnings

Strikethrough from the source tables is kept (whole-cell and partial).
"""

from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .compare import CompareOptions, CompareResult, CompareRow, RowStatus
from .models import CellOut

STATUS_LABELS: dict[str, str] = {
    "added": "Added", "deleted": "Deleted", "struck": "Struck out",
    "restored": "Restored", "changed": "Changed", "unchanged": "Unchanged",
}
ROW_FILLS = {
    "added": "E3F1E4", "deleted": "F8DEDE", "struck": "FBEEEE",
    "restored": "E1EAF6", "changed": None, "unchanged": None,
}
CHANGED_FILL = PatternFill("solid", fgColor="FCE3CC")
HEADER_FILL = PatternFill("solid", fgColor="DDE4EE")
COL_FILLS = {"added": PatternFill("solid", fgColor="CDE8CF"), "deleted": PatternFill("solid", fgColor="F3C9C9")}
OLD, NEW, GREY = "A12A2A", "1F5F23", "6B7280"
THIN = Side(style="thin", color="C9CED6")


def _fill(hex_colour: str | None) -> PatternFill | None:
    return PatternFill("solid", fgColor=hex_colour) if hex_colour else None


def _blocks(cell: CellOut | None, color: str | None = None, bold: bool = False) -> list[TextBlock]:
    """Rich-text runs for a cell, keeping its strikethrough."""
    if cell is None or not cell.t.strip():
        return [TextBlock(InlineFont(i=True, color=GREY), "(blank)")]
    if cell.s == "partial" and cell.runs:
        return [TextBlock(InlineFont(strike=r.strike, color=color, b=bold), r.text) for r in cell.runs if r.text]
    return [TextBlock(InlineFont(strike=cell.s == "full", color=color, b=bold), cell.t)]


def _write_value(ws, row: int, col: int, cell: CellOut | None):
    """An unchanged cell: the value as a number/text, with its strikethrough."""
    target = ws.cell(row=row, column=col)
    if cell is None:
        return target
    if cell.s == "partial" and cell.runs:
        target.value = CellRichText(_blocks(cell))
    else:
        target.value = cell.v if isinstance(cell.v, (int, float)) and not isinstance(cell.v, bool) else cell.t
        if cell.s == "full":
            target.font = Font(strike=True)
    return target


def compare_to_xlsx(
    result: CompareResult,
    options: CompareOptions | None = None,
    statuses: set[RowStatus] | None = None,
    columns: list[int] | None = None,
) -> bytes:
    """`statuses`: rows to include (None = all). `columns`: compare-column indices to
    include, in order (None = all); the key column is always included first."""
    opts = options or CompareOptions()
    key_idx = next(i for i, c in enumerate(result.columns) if c.is_key)
    order = [i for i in (columns if columns is not None else range(len(result.columns))) if i != key_idx]
    order = [key_idx, *order]
    rows = [r for r in result.rows if statuses is None or r.status in statuses]
    rows.sort(key=lambda r: (r.key.casefold(), r.b_row or 0, r.a_row or 0))  # sorted by key

    wb = Workbook()
    ws = wb.active
    ws.title = "Differences"
    _differences(ws, result, rows, order)
    _cell_changes(wb.create_sheet("Cell changes"), result, rows, order)
    _summary(wb.create_sheet("Summary"), result, opts, statuses, len(rows))

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _header(ws, titles: list[str]) -> None:
    for c, title in enumerate(titles, start=1):
        cell = ws.cell(row=1, column=c, value=title)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = Border(bottom=THIN)
    ws.freeze_panes = "A2"


def _differences(ws, result: CompareResult, rows: list[CompareRow], order: list[int]) -> None:
    cols = [result.columns[i] for i in order]
    titles = ["Status"]
    for c in cols:
        suffix = " (new column)" if c.status == "added" else " (removed column)" if c.status == "deleted" else ""
        titles.append(c.name + suffix)
    titles += ["Changed cells", "Old row", "New row"]
    _header(ws, titles)
    for j, c in enumerate(cols, start=2):
        if c.status in COL_FILLS:
            ws.cell(row=1, column=j).fill = COL_FILLS[c.status]
    ws.freeze_panes = "C2"  # keep status and key visible

    widths = [len(t) for t in titles]
    widths[0] = 11  # longest status label
    for r, row in enumerate(rows, start=2):
        row_fill = _fill(ROW_FILLS[row.status])
        status_cell = ws.cell(row=r, column=1, value=STATUS_LABELS[row.status])
        status_cell.font = Font(bold=row.status != "unchanged", color=GREY if row.status == "unchanged" else None)
        for j, i in enumerate(order, start=2):
            cc = row.cells[i]
            if cc.change != "none":
                arrow = TextBlock(InlineFont(color=GREY), "  →  ")
                target = ws.cell(row=r, column=j, value=CellRichText(
                    [*_blocks(cc.a, OLD), arrow, *_blocks(cc.b, NEW, bold=True)]))
                target.fill = CHANGED_FILL
                text_len = len(cc.a.t if cc.a else "") + len(cc.b.t if cc.b else "") + 5
            else:
                shown = cc.b if cc.b is not None else cc.a
                target = _write_value(ws, r, j, shown)
                text_len = len(shown.t) if shown else 0
            if row_fill and cc.change == "none":
                target.fill = row_fill
            widths[j - 1] = max(widths[j - 1], min(text_len, 60))
        n = len(order) + 2
        for k, v in enumerate([row.changed_cells or None, row.a_row, row.b_row]):
            ws.cell(row=r, column=n + k, value=v)
        if row_fill:
            for c in (1, n, n + 1, n + 2):
                ws.cell(row=r, column=c).fill = row_fill

    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = max(8, min(w + 2, 62))
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(titles))}{len(rows) + 1}"


def _cell_changes(ws, result: CompareResult, rows: list[CompareRow], order: list[int]) -> None:
    _header(ws, ["Key", "Row status", "Column", "Change", "Old value", "New value", "Old row", "New row"])
    kinds = {"value": "Value", "strike": "Strikethrough", "both": "Value and strikethrough"}
    r = 2
    for row in rows:
        for i in order:
            cc = row.cells[i]
            if cc.change == "none":
                continue
            ws.cell(row=r, column=1, value=row.key)
            ws.cell(row=r, column=2, value=STATUS_LABELS[row.status])
            ws.cell(row=r, column=3, value=result.columns[i].name)
            ws.cell(row=r, column=4, value=kinds[cc.change])
            _write_value(ws, r, 5, cc.a)
            _write_value(ws, r, 6, cc.b)
            ws.cell(row=r, column=5).fill = PatternFill("solid", fgColor="F8DEDE")
            ws.cell(row=r, column=6).fill = PatternFill("solid", fgColor="E3F1E4")
            ws.cell(row=r, column=7, value=row.a_row)
            ws.cell(row=r, column=8, value=row.b_row)
            r += 1
    for col, w in zip("ABCDEFGH", (14, 12, 22, 22, 36, 36, 9, 9)):
        ws.column_dimensions[col].width = w
    if r > 2:
        ws.auto_filter.ref = f"A1:H{r - 1}"


def _summary(ws, result: CompareResult, opts: CompareOptions, statuses, exported: int) -> None:
    s = result.summary
    lines: list[tuple[str, object]] = [
        ("Table comparison", None),
        ("Old table", result.a_label),
        ("New table", result.b_label),
        ("Exported", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Rows exported", exported if statuses is None else
         f"{exported} ({', '.join(STATUS_LABELS[x] for x in STATUS_LABELS if x in statuses)})"),
        (None, None),
        ("Rows added", s.added), ("Rows deleted", s.deleted), ("Rows struck out", s.struck),
        ("Rows restored", s.restored), ("Rows changed", s.changed), ("Rows unchanged", s.unchanged),
        ("Changed cells", s.changed_cells),
        ("Columns added", ", ".join(c.name for c in result.columns if c.status == "added") or 0),
        ("Columns removed", ", ".join(c.name for c in result.columns if c.status == "deleted") or 0),
        (None, None),
        ("Ignore case", "Yes" if opts.ignore_case else "No"),
        ("Strikethrough counts as a change", "Yes" if opts.compare_strike else "No"),
    ]
    lines += [("Warning", w) for w in result.warnings]
    for r, (label, value) in enumerate(lines, start=1):
        if label:
            ws.cell(row=r, column=1, value=label).font = Font(bold=True, size=14 if r == 1 else 11)
        if value is not None:
            ws.cell(row=r, column=2, value=value)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 70
