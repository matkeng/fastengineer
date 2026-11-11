# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The edits an import makes to its file, as a report to hand back to whoever owns the file
(the mechanical engineer, for a MEL) so the next revision can include them.

Three kinds of edit are reported, each with the note (reason) given when it was made:

- **Changed cells** (overrides): the row's key, the column, the value in the file, the value
  used and the file's row number. A column the import renamed is named as it is in the file.
- **Removed rows** (hidden rows): the row's key and its values as they are in the file.
- **Added rows** (custom rows): the key and the values entered.

An edit whose row is not in the latest file any more is listed too, marked so.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel

from .models import Recipe, Revision
from .pipeline import run_pipeline

Grid = list[list]
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _v(text: object):
    """A value as the file has it, a number as a number (so Excel doesn't flag it), text with a
    leading zero (0042) as written."""
    t = "" if text is None else str(text).strip()
    if _NUMBER.match(t) and not (len(t.lstrip("-")) > 1 and t.lstrip("-")[0] == "0" and "." not in t[:2]):
        return float(t) if "." in t else int(t)
    return t


def edits_report(rev: Revision, recipe: Recipe, made: datetime | None = None) -> list[tuple[str, Grid]]:
    """The report's sheets: [(title, rows)], the first row of each its headings."""
    key = rev.key_header
    # where each row was in the file (a revision of before this was kept has no row numbers)
    by_key = {r[key]: (rev.file_rows[i] if i < len(rev.file_rows) else None, r) for i, r in enumerate(rev.rows)}
    # the import's renames, back to the file's own header
    source_of = {(c.rename or "").strip(): c.header for c in recipe.columns if (c.rename or "").strip()}
    texts = {t.name for t in recipe.text_columns}
    # the values each column has before overrides (after renames and fixed-value columns)
    before = {r.key: r.values for r in run_pipeline(rev, recipe, "text").rows}

    # whether this file already has each edit (in the order of the sheets below)
    words = {"done": "Done in this file: can be cleared", "gone": "Row not in this file: can be cleared", "needed": ""}
    said = [st.detail if st.state == "partly" else words[st.state] for st in edits_status(rev, recipe)]
    said.reverse()

    changed: Grid = [[key, "Column", "Column in the file", "Value in the file", "Value used", "Reason", "Row in the file", "Status"]]
    for ov in recipe.overrides:
        row = by_key.get(ov.key)
        in_file = source_of.get(ov.column, ov.column)
        if ov.column in texts and in_file not in rev.headers:
            in_file = "(a column the import adds)"
        was = before[ov.key].get(ov.column, "") if ov.key in before else (row[1].get(in_file, "") if row else "")
        status = said.pop()
        changed.append([ov.key, ov.column, in_file, _v(was), _v(ov.value), ov.note, row[0] if row else None, status])

    removed: Grid = [[key, "Reason", "Row in the file", "Status", *[h for h in rev.headers if h != key]]]
    for h in recipe.hidden_rows:
        row = by_key.get(h.key)
        values = [_v(row[1].get(c, "")) for c in rev.headers if c != key] if row else []
        removed.append([h.key, h.note, row[0] if row else None, said.pop(), *values])

    columns = list(dict.fromkeys(c for r in recipe.custom_rows for c in r.values))
    added: Grid = [[key, "Reason", "Status", *columns]]
    for r in recipe.custom_rows:
        added.append([r.key, r.note, said.pop(), *[_v(r.values.get(c, "")) for c in columns]])

    made = made or datetime.now()
    summary: Grid = [
        ["Edits made by the import", recipe.name],
        ["List", recipe.target],
        ["File", rev.file_name],
        ["Revision", rev.rev],
        ["Uploaded", rev.uploaded_at.strftime("%Y-%m-%d %H:%M")],
        ["Key column", key],
        ["Changed cells", len(recipe.overrides)],
        ["Removed rows", len(recipe.hidden_rows)],
        ["Added rows", len(recipe.custom_rows)],
        ["Report made", made.strftime("%Y-%m-%d %H:%M")],
        ["Row in the file", "1 is the first row under the headings"],
        [],
        ["These are the changes the import makes to the file. Please take them into the next revision, so the import no longer has to."],
    ]
    return [("Summary", summary), ("Changed cells", changed), ("Removed rows", removed), ("Added rows", added)]


# -- has the file taken the edits in? ------------------------------------------------------------

class EditStatus(BaseModel):
    """Whether the latest file has taken one edit in.

    `state`: "done" (the file now has it: the edit changes nothing and can be cleared),
    "gone" (a changed cell whose row isn't in the file: nothing to change, can be cleared),
    "partly" (an added row the file now has, with some values different), or "needed" (the
    import still has to make it)."""
    kind: str  # "changed" / "removed" / "added"
    key: str
    column: str = ""
    note: str = ""
    state: str
    detail: str


def _same(a: object, b: object) -> bool:
    """Values compare as numbers where both are numbers (40 = 40.0), else as text, trimmed."""
    x, y = ("" if a is None else str(a).strip()), ("" if b is None else str(b).strip())
    if x == y:
        return True
    try:
        return float(x) == float(y)
    except ValueError:
        return False


def edits_status(rev: Revision, recipe: Recipe) -> list[EditStatus]:
    """Each edit of the import against its latest file, in the order of the report."""
    key = rev.key_header
    keys = {r[key] for r in rev.rows}
    before = {r.key: r.values for r in run_pipeline(rev, recipe, "text").rows}  # the file's values, as the import names its columns
    hidden = {h.key for h in recipe.hidden_rows}
    out: list[EditStatus] = []
    for ov in recipe.overrides:
        if ov.key not in keys:
            state, detail = "gone", "The row is not in the file any more"
        elif ov.key in hidden:
            state, detail = "needed", "The row is removed by the import too"
        else:
            now = before.get(ov.key, {}).get(ov.column, "")
            if _same(now, ov.value):
                state, detail = "done", f"The file now has {ov.value or '(blank)'}"
            else:
                state, detail = "needed", f"The file still has {now or '(blank)'}; the import uses {ov.value or '(blank)'}"
        out.append(EditStatus(kind="changed", key=ov.key, column=ov.column, note=ov.note, state=state, detail=detail))
    for h in recipe.hidden_rows:
        done = h.key not in keys
        out.append(EditStatus(kind="removed", key=h.key, note=h.note, state="done" if done else "needed",
                              detail="The row is not in the file any more" if done else "The row is still in the file"))
    file_rows = {r.key: r.values for r in run_pipeline(rev, recipe.model_copy(update={"overrides": []}), "overrides").rows}
    for c in recipe.custom_rows:
        if c.key not in keys:
            out.append(EditStatus(kind="added", key=c.key, note=c.note, state="needed", detail="The row is not in the file yet"))
            continue
        have = file_rows.get(c.key, {})
        diff = [f"{col}: file {have.get(col, '') or '(blank)'}, import {v}" for col, v in c.values.items() if not _same(have.get(col, ""), v)]
        out.append(EditStatus(kind="added", key=c.key, note=c.note, state="partly" if diff else "done",
                              detail=("The file has the row, but " + "; ".join(diff)) if diff else "The file has the row, with these values"))
    return out
