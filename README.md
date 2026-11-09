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
| §12 GitHub Actions build on `windows-latest` | `.github/workflows/windows-build.yml` |

The app has two tabs:

- **Excel query**: a step-by-step wizard that turns a worksheet or Excel table
  into a reviewable, keyed table (see below).
- **Compare tables**: pick an old and a new table with the same wizard and see
  what changed between them (see below).
- **MEL import**: turn an equipment list into a load list with a saved,
  re-applicable recipe of rules (see below).
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

## MEL import

Implements the import recipe described in [`docs/PRD_MEL_IMPORT.md`](docs/PRD_MEL_IMPORT.md)
(originally a Django app) as a desktop feature. Core logic:
`core/src/workbench_core/mel/`; API: `desktop/engine/workbench_desktop/mel_api.py`;
UI: `web/src/components/mel/`.

1. **Create an import** (MEL, ELL, EEL, PIL or LIL) and **upload a file**: a CSV
   (UTF-8, or Windows-1252 with a warning; `,` `;` tab or `|` separated), or a
   sheet or table from Excel through the import wizard. Choose the key column
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
   | 7 | Mapping | load-list field <- column or fixed value |

3. **Result**: the combined table and the load list, with filters, and export
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

## Lists & tables

Reference data you define and keep (`core/src/workbench_core/refdata/`, API
`desktop/engine/workbench_desktop/refdata_api.py`, UI `web/src/components/ref/`).

- **Lists** (enums): a unique name, and items with a **code**, **value** and
  **description**. Codes and values are unique within the list (ignoring case);
  items can be reordered.
- **Tables**: a unique name and columns of type **Text**, **List (enum)**,
  **Whole number**, **Yes / No** or **Decimal**, each optionally *required* and/or
  *unique*. Rows are added, edited and deleted in a form with the right input for
  each type, and listed in a filterable grid (lists and Yes/No get drop-down
  filters) with Copy/CSV.
- Names are unique across lists and tables, ignoring case and extra spaces.
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

CI also drives the Excel flow against the compiled engine. To regenerate the
sample workbook (uses LibreOffice, if installed, to calculate formula results):
`python scripts/make_sample_workbook.py`.

## Things to check on a Windows test machine

- Installs per-user without admin (NSIS) and silently via MSI.
- First launch: engine connects (status turns green). The connect time
  includes Nuitka onefile extraction and any antivirus scan; note it.
- Closing the window leaves no `workbench-engine.exe` in Task Manager.
  (The engine also watches the shell's PID and exits if the shell dies.)
- If the engine never connects, check `%TEMP%\workbench-engine.log`.
