# Drawing Workbench — hello-world proof of concept

A minimal, end-to-end slice of the *Drawing Workbench* architecture, built to
prove the stack installs and runs as a Windows `.exe`:

```
Tauri 2 shell (Rust, WebView2)
 ├─ Vue 3 + TypeScript + Pinia front end      web/
 └─ Python engine sidecar (Nuitka-compiled)   desktop/engine/  →  FastAPI on 127.0.0.1:<free port>
      └─ workbench_core (no web framework)    core/
```

What it demonstrates:

| Spec item | In this PoC |
|---|---|
| §3 Tauri 2 shell, NSIS `Setup.exe` + MSI, WebView2 bootstrapper bundled | `desktop/src-tauri/tauri.conf.json` |
| §3 Python sidecar compiled with Nuitka, launched on a free port, stopped on exit | `desktop/src-tauri/src/lib.rs`, `desktop/engine/` |
| §5 Framework-free `workbench_core` with a thin FastAPI adapter | `core/`, `desktop/engine/workbench_desktop/app.py` |
| §4 Vue 3 + Pinia shared store | `web/src/stores/workbench.ts` |
| §7 Pydantic document model with stable UUIDs | `core/src/workbench_core/model.py` |
| §6 Excel table extraction (openpyxl) with a DataTables review grid | `core/src/workbench_core/excel/`, `web/src/components/excel/` |
| Symbol detection (OpenCV, PDFium) and tag reading (PDF text / Windows OCR) | `core/src/workbench_core/symbols/`, `web/src/components/symbols/` |
| §12 GitHub Actions build on `windows-latest` | `.github/workflows/windows-build.yml` |

The app's tabs:

- **Excel query**: a step-by-step wizard that turns a worksheet or Excel table
  into a reviewable, keyed table (see below).
- **Compare tables**: pick an old and a new table with the same wizard and see
  what changed between them (see below).
- **Symbol detection**: find any symbol on PDF drawings (templates matched with
  OpenCV, tags read from the PDF text or with Windows OCR) and produce a tags
  list; ships with a P&ID instrument example (see below).
- **List import**: turn an equipment list into a load list, or a tags list
  into an instrument list, with a saved, re-applicable recipe of rules (see below).
- **Lists & tables**: your own enumerated lists and typed tables (see below).
- **Engine**: engine status (port, Python version, whether it's
  Nuitka-compiled, PID), a "say hello" round-trip to Python, and a few demo
  model objects.

## Excel query wizard

| Step | What happens |
|---|---|
| 1. Workbook | Drop or browse for an `.xlsx`/`.xlsm` file, or use the bundled sample (`samples/cable-schedule-sample.xlsx`). The engine reads it locally. |
| 2. Sheet or table | Pick a whole worksheet or a defined Excel table. |
| 3. Header row | Pick the header row from a list or by clicking it in a preview grid. A suggestion is pre-selected. Stacked headers ("Cable" above "Size" and "Cores") can span up to 4 rows and are joined into "Cable Size", "Cable Cores". |
| 4. Key column | Pick the key index column (e.g. tag or cable number). Fill, uniqueness and duplicate counts are shown for each column, and a likely key is suggested. Rows with a blank key can be skipped. |
| 5. Results | A DataTables grid with paging, sorting, a global search, a filter on every column, a strike filter, a **Columns** button to show or hide columns, and Copy/CSV export. |

How cells are read (`core/src/workbench_core/excel/`):

- **Values, not formulas.** The engine reads the results Excel calculated and
  saved in the file. If a formula has no saved result (for example the file was
  written by a script and never opened in Excel), the cell is blank and a
  warning says how many. Open and save the file in Excel to fix that.
- **Merged cells** are split out: every cell in a merged range gets the
  top-left value. Copied values are shown in italics in the preview.
- **Strikethrough** is detected per cell as *none*, *partial* (only some of
  the text is struck, e.g. `~~16~~ 25 mm²`) or *full*, and shown as struck
  text in the grid. Each row also gets a status: *Struck out* if every filled
  cell is fully struck, *Partly struck* if any cell is struck.
- Duplicate keys are flagged with ⚠, and every row keeps its Excel row number.

Not covered yet: `.xls` and `.xlsb` (no formatting information, so strike
can't be detected), strikethrough applied by conditional formatting, and very
large sheets (the whole sheet is loaded into memory).

## Getting the Windows installer

**Easiest: from CI.** Every push runs the
*Drawing Workbench - Windows build* workflow. Open the run in the repo's
**Actions** tab and download the `drawing-workbench-windows` artifact. It contains:

- `Drawing Workbench_0.1.0_x64-setup.exe` (NSIS installer)
- `Drawing Workbench_0.1.0_x64_en-US.msi` (for silent/IT deployment: `msiexec /i <file>.msi /qn`)

The builds are **unsigned**, so SmartScreen will say "Windows protected your
PC": click *More info → Run anyway*. Code signing (spec §3) is a later step.

**Locally on Windows.** Install Python 3.11+, Node 20+, Rust (`rustup`, MSVC
toolchain) and Visual Studio Build Tools with the C++ workload, then:

```powershell
pwsh scripts/build-windows.ps1
```

Installers land in `desktop/src-tauri/target/release/bundle/{nsis,msi}/`.
The first Nuitka build takes several minutes; later builds are cached.

## Development

```powershell
# 1. Build the sidecar once (Tauri checks the binary exists even in dev).
pwsh scripts/build-engine.ps1     # or scripts/build-engine.sh on macOS/Linux

# 2. Run the desktop app with hot reload (starts Vite for you).
cd web; npm install
cd ../desktop; npm install; npx tauri dev
```

Front-end only, in a browser, against an interpreted engine:

```bash
git clone <this repo> && cd <repo>
python -m venv .venv && .venv/bin/pip install -e core -e desktop/engine   # Windows: .venv\Scripts\pip
.venv/bin/python -m workbench_desktop --port 8765
cd web && npm install && npm run dev        # open http://localhost:5173
```

## Compare tables

Choose the **old** table and then the **new** table, each with the import wizard
(workbook, sheet or table, header row, key column). They can come from two
workbooks or two sheets of one ("Use the same workbook as the old table").
Samples: `samples/cable-schedule-sample.xlsx` (Rev C) and
`samples/cable-schedule-sample-revD.xlsx` (Rev D).

Rows are matched by **key value** and columns by **header name**, so row and
column order don't matter. Each row gets a status:

| Status | Meaning |
|---|---|
| Added | key only in the new table |
| Deleted | key only in the old table |
| Struck out | marked deleted in the new table (every filled cell, or the key cell, fully struck through) but not in the old |
| Restored | struck out in the old table, no longer in the new |
| Changed | one or more cells differ in value or in strikethrough |
| Unchanged | |

Changed cells show `old → new`. Added and removed columns are labelled in the
header. The grid opens on **Any change**; the summary chips filter by status,
**Changed columns only** hides columns with no differences, and Copy/CSV export
what's visible (changed cells as `old → new`).

**Excel (.xlsx)** exports the rows and columns currently shown (status filter
and visible columns) to a formatted workbook: a Save As dialog in the desktop
app, a download in a browser. It has three sheets:

- **Differences**: one row per key, sorted by key and coloured by status; changed
  cells as `old → new` (old in red, new in green); added and removed columns
  labelled; the source strikethrough kept, including partial strikes;
  filters and frozen header.
- **Cell changes**: one row per changed cell (key, column, kind of change, old,
  new, Excel rows), for filtering and review.
- **Summary**: the two tables, counts, options and warnings.

Comparison rules (`core/src/workbench_core/excel/compare.py`): keys, header names
and text are compared ignoring case and extra spaces (switchable); numbers are
compared as numbers (`2.50` = `2.5`); a change in strikethrough counts as a
change (switchable), but not on rows that were struck out or restored as a
whole, where the row status already says so. Duplicate keys are paired in the
order they appear, with a warning.

## Symbol detection

Finds any symbol on PDF drawings and reads the text tag written in or beside it. It ports
the symbol-detection app in [`docs/PRD_SYMBOL_DETECTION.md`](docs/PRD_SYMBOL_DETECTION.md)
(originally Django and Celery). Nothing in it is specific to P&IDs: templates and tag rules
live in **libraries**, one per kind of drawing. The app ships with a ready-made
**P&ID instruments (ISA)** library as the example; it is added on first start, and
*Add the P&ID example* restores it.

Core logic: `core/src/workbench_core/symbols/` (OpenCV, NumPy and PDFium via pypdfium2,
imported only when used). API: `desktop/engine/workbench_desktop/symbols_api.py`. UI:
`web/src/components/symbols/`.

1. **Library.** Each library has:
   - a **tag pattern**, a regular expression whose named groups become columns of the tags
     list (for P&IDs: `function`, `loop`, `suffix`);
   - a **tag format** that writes every tag the same way (`{function}-{loop}{suffix}`);
   - a **text scan** option, which finds tags anywhere in the page text, as one word or as
     two words stacked as in a bubble;
   - the threshold for new templates, when to use OCR, and **ignored text** (words, and areas
     such as the title block, drawn once).

   Leave the pattern blank to take template tags exactly as written. Libraries can be
   created, copied, exported and imported as JSON.
2. **Add PDFs** into a library. Each page is rendered once at 200 DPI to a lossless PNG,
   with the page's rotation applied, and its text-layer words are mapped into the same pixel
   frame (`<data dir>/symbols/<drawing>/`).
3. **Templates.** On a page, choose **New template** and drag a box around a symbol. It is
   cut with the page text erased and trimmed to the linework. You can also add a symbol
   image file. In the template editor:
   - click where each part of the tag is written;
   - set the **threshold**; any page can override it, or skip the template;
   - choose the rotated, mirrored and size variants;
   - choose what is compared: **the symbol's lines** (widened by N px, so pipes or text
     crossing it don't count), **a custom mask** you paint or erase (or upload as an
     image) to ignore parts that vary, or **the whole rectangle**;
   - press **Test on page** to see the matches and scores with the unsaved settings and
     mask.

   Templates run in priority order, and each match is blanked before the next template runs.
4. **Analyse** ticked drawings in the background, with progress and cancel. Text comes from
   the PDF, or **Windows' built-in OCR** on scanned sheets. Nothing is bundled for OCR.
5. **Tags list.** One row per unique tag: `Tag`, the pattern's groups, `Count, Drawings,
   Sheets, Symbols, Source`. Export it to `.xlsx` (with a per-symbol *Detections* sheet) or
   `.csv`, or **Send to a list import**. For P&IDs that is a `PIL` import mapping onto
   instrument-list fields (`tag`, `loop`, `instrument_type`, `signal_type`, …), whose saved
   rules re-apply after every re-analysis.

Samples (`python scripts/make_sample_pid.py`, which also rebuilds the built-in example
library `core/src/workbench_core/symbols/starter.py`):

- `samples/pid-sample.pdf`: two sheets, the second with `/Rotate 90`. It has 11 unique
  tags and a title block with tag-like text.
- `samples/pid-sample-scanned.pdf`: the same sheets, image only.
- `samples/pid-library.json`: the example library as a file.

Fixed compared with the PRD's code (its §11):

- The per-page overrides work (#1).
- Every box is in one pixel frame, including on rotated pages and above the 80 MP
  downscale guard (#3, #4).
- Matching compares binarised ink against binarised ink with mean-subtracted normalised
  correlation under the mask, computed with FFTs, so scores aren't high everywhere (#14).
- Peaks are chosen by score with non-max suppression (#11). A template with too many
  candidates is reported, not silently dropped (#12).
- Renders and templates are PNG (#13).
- An uploaded or painted mask is kept and used (#5). Viewing a template writes nothing
  (#6).
- Priority is an explicit move (#7). Tags are resolved at analysis time, and templates are
  referenced by id (#8, #9).
- The OCR fallback (§12 #7) and click-to-place tag points (§12 #5) are included.
- Border auto-detection, the blob/cloud/line-removal matchers and Google OCR are not.

## List import (MEL → load list, PIL → instrument list)

Implements the import recipe described in [`docs/PRD_MEL_IMPORT.md`](docs/PRD_MEL_IMPORT.md)
(originally a Django app) as a desktop feature. Core logic:
`core/src/workbench_core/mel/`; API: `desktop/engine/workbench_desktop/mel_api.py`;
UI: `web/src/components/mel/`.

1. **Create an import** (MEL, ELL, EEL, PIL or LIL) and **upload a file**: a CSV
   (UTF-8, or Windows-1252 with a warning; `,` `;` tab or `|` separated), a
   sheet or table from Excel through the import wizard, or the tags list of a
   symbol-detection run. Choose the key column
   (usually the equipment tag). Headers and keys are made unique: blank ->
   `Blank`, repeats -> `_1`, `_2`.
2. **Build the recipe**. Rules run in this order every time the data is read,
   and the uploaded file is never changed:

   | # | Editor | Rule |
   |---|---|---|
   | 1 | Columns | hide or rename columns (not the key) |
   | 2 | Rows | hide rows by key |
   | 3 | Text columns | add a column with the same value in every row |
   | 4 | Overrides | click a cell to replace its value |
   | 5 | Custom rows | add rows that aren't in the file |
   | 6 | Calculated | `if / then / else / on error` per row; `<<Column>>` refers to a column |
   | 7 | Mapping | load-list (MEL) or instrument-list (PIL) field <- column or fixed value |

3. **Result**: the combined table and the load list (or instrument list), with filters, and export
   to CSV or Excel (.xlsx; overridden cells, custom rows and errors highlighted,
   plus a Notes sheet).
4. **Save**. Edits are a draft (previewed live) until you press Save. Saved
   imports and every uploaded revision are kept in a local SQLite database, so
   they are there next time; the Engine tab shows where
   (`%APPDATA%\com.drawingworkbench.poc\workbench.db` on Windows).
5. **Revised file**: upload it as the next revision; the newest is used and the
   same rules are applied. The Overview lists any rule that no longer applies
   (for example a hidden row whose tag is not in the new file).

Samples: `samples/mel-sample.csv` and `samples/mel-sample-rev2.csv`.

Differences from the PRD's implementation, from its known-issues list (§11):

- Calculated columns bind `<<Column>>` values as variables instead of pasting
  text into the expression, so values can't change the formula and text needs
  no quotes (`<<Type>> == 'Pump'`); plain text like `Motor` is used as is.
- A recipe is saved as one document (no partial saves); editing a custom row
  replaces it; renamed columns keep their position; the key column can differ
  per revision; a recipe with no file shows a message instead of failing;
  orphaned rules are reported (the PRD's suggested "rule health" panel).
- Numeric load-list fields that aren't numbers are kept as text and counted in a
  warning, rather than replaced with `-9999`.
- Not included: pushing into a load-list database (there isn't one here yet;
  export instead) and Transpose columns (not applied in the PRD either).

## Lists, trees & tables

Reference data you define and keep (`core/src/workbench_core/refdata/`, API
`desktop/engine/workbench_desktop/refdata_api.py`, UI `web/src/components/ref/`).

- **Lists** (enums): a unique name, and items with a **code**, **value** and
  **description**. Codes and values are unique within the list (ignoring case);
  items can be reordered.
- **Trees**: like lists, but every item can sit under another item of the same
  tree (a parent reference), e.g. area → unit → system. Codes are unique in the
  tree; values are unique among the items at the same level. The editor shows
  the hierarchy with expand/collapse and a filter; codes, values and
  descriptions are edited in place; items are re-arranged by **drag and drop**
  (drop on the top or bottom edge of a row to place before/after it, on the
  middle to put it inside; an item can't be dropped into itself) or with the
  row buttons / Alt+arrow keys (indent, outdent, move up/down). Changes are a
  draft until Save, like lists.
- **Tables**: a unique name and columns of type **Text**, **List (enum)**,
  **Whole number**, **Yes / No** or **Decimal**, each optionally *required* and/or
  *unique*. Rows are added, edited and deleted in a form with the right input for
  each type, and listed in a filterable grid (lists and Yes/No get drop-down
  filters) with Copy/CSV.
- Names are unique across lists, trees and tables, ignoring case and extra spaces.
- Values are validated by the engine: whole numbers and decimals must be numbers
  (decimals are stored exactly, e.g. `2.50` -> `2.5`), list cells must be an item
  of that list (a code or value is accepted and stored as the item).
- List cells store the item's id, so renaming an item's code or value updates
  every row that uses it. An item, or a list, that rows or columns use can't be
  deleted; the message says where it's used.
- Changing a column's type converts the existing rows (text `12` -> 12, list
  item -> its code as text, a code -> an item of the new list); if any value
  can't be converted, or a new required/unique rule doesn't hold, nothing is
  saved and the problem values are listed.
- Everything is stored in the same local database as MEL imports, so it's there
  next time the app starts.

## Tests

```bash
.venv/bin/pip install -e core -e "desktop/engine[test]"
.venv/bin/python -m pytest core/tests desktop/engine/tests
```

CI also drives the Excel, compare, MEL, lists and symbol-detection flows (including
Windows OCR on the scanned sample) against the compiled engine.

## License

Open core: this repository is licensed under the **GNU Affero General Public License v3.0
only** ([`LICENSE`](LICENSE)), copyright © 2026 Matthew Kelly; commercial licenses and
proprietary add-ons are available from the copyright holder. See
[`LICENSING.md`](LICENSING.md) for what that means, and [`CONTRIBUTING.md`](CONTRIBUTING.md) for
the terms contributions are accepted under.

Third-party components are listed in
[`docs/THIRD_PARTY_LICENSES.md`](docs/THIRD_PARTY_LICENSES.md). All of them are permissive (or
file-level MPL) and compatible with the AGPL. They are kept that way so that commercial
editions remain possible, which is why the app uses pypdfium2 rather than PyMuPDF and leaves
OpenCV's LGPL FFmpeg plug-in out of the build. The installer shows the license, and the
portable folder includes `LICENSE.txt` and the third-party report. To regenerate the
sample workbook (uses LibreOffice, if installed, to calculate formula results):
`python scripts/make_sample_workbook.py`.

## Things to check on a Windows test machine

- Installs per-user without admin (NSIS) and silently via MSI.
- First launch: engine connects (status turns green). The connect time
  includes Nuitka onefile extraction and any antivirus scan; note it.
- Closing the window leaves no `workbench-engine.exe` in Task Manager.
  (The engine also watches the shell's PID and exits if the shell dies.)
- If the engine never connects, check `%TEMP%\workbench-engine.log`.
- Symbol detection: the **OCR** status is shown in a library's *Settings*. Windows OCR needs an OCR-capable display language (Settings > Time &
  language); on a scanned sheet, a missing language shows as a page warning.
