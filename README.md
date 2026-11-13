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

- **Compare tables** is not a tab of its own: it is opened from its card on the
  **Dashboard**, which everyone sees (and has a **← Dashboard** button to go back). Pick an old and
  a new table with the Excel wizard and see what changed between them (see below).
- **Symbol detection**: find any symbol on PDF drawings (templates matched with
  OpenCV, tags read from the PDF text or with Windows OCR) and produce a tags
  list; ships with a P&ID instrument example (see below).
- **List import**: turn an equipment list into a load list, or a tags list
  into an instrument list, with a saved, re-applicable recipe of rules (see below).
- **Project lists**: the key lists every project has: Plant Areas, Equipment
  Packages, Load Types, Equipment Codes, Instrument Codes and the Load List
  (see below).
- **Engine**: engine status (port, Python version, whether it's
  Nuitka-compiled, PID), a "say hello" round-trip to Python, and a few demo
  model objects.

## Excel query wizard

> The **Excel query** tab has been removed. The wizard itself is still how a
> sheet or table is chosen in **Compare tables** and in **List import** ("From
> Excel…"), so the steps below describe it there.

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

## Multi-user: one shared server for a team

Options for connecting the app to Microsoft SharePoint (not built yet) are in
[`docs/SHAREPOINT_INTEGRATION.md`](docs/SHAREPOINT_INTEGRATION.md).

Out of the box each person has their own data on their own PC. For a team, run
**one engine on a server** and point everyone's desktop app at it. Everyone then
works on the same data at the same time, and the app records **who changed which
record, when, and what changed**.

### On the server

1. Take `workbench-engine.exe` from the portable zip and copy it to the server.
2. Run it as a service (for example with [NSSM](https://nssm.cc), or a Task
   Scheduler task that runs at start-up):

   ```
   workbench-engine.exe --server --host 0.0.0.0 --port 8765 --data-dir D:\WorkbenchData --admin ACME\jsmith
   ```

   `--server` makes every change name its user. `--data-dir` holds the
   projects, one folder each. `--admin` names a user
   who may manage projects; repeat it for more than one (see Projects below).
3. Keep `--data-dir` on a **local disk of the server**, not a network share: the
   database is not safe on a share. Only the engine opens it; nobody else needs
   file access to that folder.
4. Allow inbound TCP 8765 in Windows Firewall, for your office network only.
5. Back up the `--data-dir` folder, and any project folders kept elsewhere.

### On each PC

1. Install the app as usual (MSI or setup exe).
2. Tell it where the server is, in either of these ways (both can be rolled out
   by Group Policy):
   - a file `C:\ProgramData\DrawingWorkbench\client.json` containing
     `{"server_url": "http://SERVERNAME:8765"}` (applies to every user of the PC), or
   - an environment variable `WORKBENCH_SERVER_URL=http://SERVERNAME:8765`.
3. Start the app. There is no login screen: it uses the Windows login of whoever
   is signed in (`DOMAIN\username`) and the PC's name. The status bar shows
   "shared server" and the user name.

Without either setting the app works as before, with its own private engine and
data. Changes are still logged, under the local Windows login.

### Projects

Each project is a **folder that is complete on its own**. It holds the project's
database (`workbench.db`) and uploaded drawings, and that database holds
everything about the project: its lists, tables, symbol libraries, imports,
generators and change log, and also its own name, members and archived flag.
There is no central list of projects, and nothing is shared between projects.

- **A project folder can be copied, moved, backed up or restored by itself.**
  Open it with another engine (another server, or the app on a single PC) and
  its name, members, data and history all come with it. Stop the engine, or at
  least make sure nobody is working in the project, before copying its folder,
  and copy the whole folder.
- **Which folders an engine serves:**
  - its data folder itself: the project "Default", where data lived before
    projects,
  - every folder under `<data-dir>\projects\`. Put a project folder there and
    it is found at the next start, with no other step,
  - folders elsewhere that an administrator adds on the Projects page, for
    example `E:\Jobs\Plant A`. These must be on a local disk of the machine the
    engine runs on, not a network share. If such a folder is not there at
    start-up (moved, or a disk not connected) the Projects page says so; the
    other projects are not affected.
- **Choosing a project.** The title bar has a Project box listing the projects
  you can open. The app starts in the project you had open last. Switching
  project reloads the app in the other one.
- **Administrators** (the `--admin` users; on a single PC without a server, you)
  get a **Projects** page where they:
  - create a project, in a new folder named after it under
    `<data-dir>\projects\` or in a folder they choose. It starts empty, or with
    a copy of the lists, trees, tables, symbol libraries and card and rack
    types of an existing project (the two are independent afterwards),
  - open an existing project folder as it is,
  - choose each project's **members**. People only see and open the projects
    they are a member of; administrators can open all of them. Someone in no
    project is told to ask an administrator, and shows up in the list of people
    to add once they have started the app,
  - rename, archive and restore projects. Archiving hides a project from
    everyone and deletes nothing,
  - take a project kept outside the data folder off the list. Its folder is
    left as it is.

  Each of these is recorded in that project's own change log.
- **A copy of a project** opened beside the original becomes a separate
  project with the same name and members, and can then be renamed.
- **What the engine itself keeps** (`engine.db` in the data folder) is only the
  extra folder locations and which project each user had open last. Losing it
  loses no project data.
- If the server is started **without any `--admin`**, nobody can manage
  projects and every project is open to everyone.

### What users see

- **Change log** (in the menu bar): every create, change and delete with the
  time, user, PC, and the old and new value of each changed field. Filter by
  user, record type and date. The **History** button on a list, tree, table,
  list import, symbol library, template or generator shows that record's history
  (a table's history includes its rows).
- **Changed by someone else**: if two people have the same record open and both
  save, the second save is refused, with the name of whoever saved first and
  when. Nothing is overwritten silently. Open the record again to get their
  version, then make the change again. Editing *different* records, or different
  rows of the same table, at the same time is fine.
- Exports are saved on the PC of the person exporting, as before.

### Limits to know about

- The user name is **reported by the desktop app, not verified** by the server.
  It reliably tells colleagues apart on a trusted office network; it is not a
  security control, and someone with network access and technical skill could
  send another name. There are no passwords. Project membership rests on the
  same reported name, so it keeps people in the right project but does not
  protect a project from someone determined to get in.
- Traffic is plain HTTP. Keep the port closed to anything outside the office
  network, or put the engine behind a reverse proxy with HTTPS.
- Large computed data is logged by its details, not its contents: uploaded files
  (name and size), lookup tables of a generator (row and column counts), builds
  and detection runs (that they were made or deleted, and by whom).
- A very large change (more than 200 fields in one save) lists the first 200.
- Symbol detection runs one job at a time on the server, so jobs from several
  people queue.
- For development or a test without the desktop app, open the front end in a
  browser with `?user=NAME` to stand in for the Windows login.

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
   - a **text scan** option (off in a new library, and in the example library, until you
     switch it on in the library's Settings), which finds tags anywhere in the page text, as one word or as
     two words stacked as in a bubble;
   - the threshold for new templates, when to use OCR, and **ignored text** (words, and areas
     such as the title block, drawn once).

   On a drawing's page, every piece of text that was read (from the PDF, or by OCR) is
   marked with a light yellow see-through box, so you can see what the app can read. The
   **Text** tick box beside the page turns the boxes off.

   Leave the pattern blank to take template tags exactly as written. Libraries can be
   created, copied, exported and imported as JSON.
2. **Add PDFs** into a library. Each page is rendered once at 200 DPI to a lossless PNG,
   with the page's rotation applied, and its text-layer words are mapped into the same pixel
   frame (`<data dir>/symbols/<drawing>/`).
3. **Templates.** Press **Draw on a drawing** in the sidebar (or **New template** on any
   page) and drag a box around a symbol. Adjust the box with its handles; a preview shows
   the template that will be cut (trimmed to the linework, outlined in green on the sheet)
   with its text in yellow boxes, and its size, before you create it. You can also add a
   symbol image file. In the template editor:
   - click where each part of the tag is written: a template cut from a page shows that
     page's text, each piece in a yellow box (**Show text**), and the points table says
     what each point reads there. The text is only for show: the template is matched with
     its text erased, so a bubble matches whatever tag is written in it. (Templates cut
     before this change, and image files, have no text kept: cut them again to see it.);
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
5. **Review drawings.** When the analysis finishes it opens on the drawing pages, with
   every detection highlighted (step through the run's pages from the toolbar). Click a box
   and mark it as a **false positive** (a symbol, or a text-scan tag): it turns grey and
   crossed out, and **Restore** undoes it. **Add missed** places a symbol the matcher
   didn't find: pick its template and click on it. The box snaps to the template's best
   match near the click, and the tag is read from the template's tag points (type it if
   nothing is read). Corrections are kept with the drawing page, so every later analysis of
   that page applies them again, and the run's tags list, export and list import update
   at once. The plain page viewer offers the same corrections on a page's latest result.
6. **Tags list.** One row per unique tag: `Tag`, the pattern's groups, `Count, Drawings,
   Sheets, Symbols, Source`. Export it to `.xlsx` (with a per-symbol *Detections* sheet) or
   `.csv`, or **Send to a list import**. For P&IDs that is a `PIL` import mapping onto
   instrument-list fields (`tag`, `loop`, `instrument_type`, `signal_type`, …), whose saved
   rules re-apply after every re-analysis.

**Scanned drawings (OCR) — known limit.** Searchable PDFs use their text layer and read
every tag (11/11 on the sample). On scanned, image-only sheets Windows' built-in OCR reads
loop numbers, longer codes and one-word tags (`1023`, `LIC-1030`, `PSV-1040`) but usually
drops 2-letter function codes inside bubbles (`FT`, `PT`), so those tags come out as the
number only; fix them with List-import overrides. Page text is OCR'd from a copy with the
linework removed, and symbols with missing tag parts are re-read on their own, enlarged.

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

- **Calculated columns** check conditions in order: **If**, then any number of
  **Else if** (added with **+ Else if**, reordered and removed on their rows);
  the first condition that holds gives the value, and a row where none does
  gets the **Else** value. Each condition has a **NOT** box that uses its
  opposite. A recipe saved before Else if and NOT reads as it did. A condition
  or value that can't be worked out for a row (for example a blank compared with
  a number) gives the **On error** value.
- **Show the functions you can use** on the Calculated step lists the text and
  number functions, grouped (columns and values, comparisons and logic,
  numbers, text), each with an example and its result on a sample row; a search
  box narrows the list, and clicking an example inserts it into the field you
  were last in (`GET /api/mel/functions`; `core/src/workbench_core/mel/functions.py`).
  The tests run every example, so the results shown are what the app gives.
- Expressions are held to a strict allowlist (`mel/functions.py`): only the
  functions, text functions (`.upper()`, `.split()`, …), names and operators the
  help lists. Anything else — any other function, `.` names such as
  `__class__`, `import`, `lambda`, f-strings, comprehensions, keyword arguments —
  is refused before it runs, with the reason. Sizes are capped too (expression
  length, text padding, `%` widths, `replace` results, powers), so a formula
  can't read a file or tie up the engine (before, `open(...)` could read a file
  on the engine's machine). The preview reports a **Not allowed** issue, and
  saving a recipe or reading settings with one is refused (422) naming the
  column and the field. A value with no `<<Column>>` that isn't an allowed
  expression is plain text and is never run.
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

### Passing an import's settings to a colleague

An import's settings can be saved as a `.json` file and read in by someone else,
in another project or on another PC.

- **Export settings** (on an open import) saves its column rules, hidden rows,
  text columns, overrides, added rows, calculated columns and mapping, with the
  import's name and kind of list. The uploaded files are not in it. It exports
  what is saved, so save or discard changes first.
- **Import settings…** (on an open import) replaces that import's settings with
  the file's, after you confirm. They arrive as unsaved changes: **Save** keeps
  them, **Discard** brings the old settings back. The name and the uploaded
  files stay. The file must be for the same kind of list.
- **New from settings…** (on the list of imports) makes a new import with the
  file's name and settings; you then upload its file.
- Rules that name a key or column the receiving file doesn't have are listed
  under "rules not applied" on the import's overview, as for any revised file.

### Strike-through rows

A row struck through in the MEL is a deleted row, so a **MEL** import always
gets one more column, **Strike through**, after the file's own
(`mel/ingest.py`, `strike_status`), saying how much of each row is struck
through in Excel:

| Value | When |
|---|---|
| Full Row | every filled cell of the row is wholly struck through |
| Multiple Cells | two or more cells are struck through (wholly, or one wholly and others in part) |
| One Cell | one cell is wholly struck through |
| Partial Cell/s | only part of the text of one or more cells is struck through |
| (blank) | nothing is struck through |

Only an Excel file has the formatting: a CSV upload gets the column blank,
with a warning saying so. The column is like any other: filter on it in Rows
to untick struck-through rows, or use it in a calculated column (e.g.
`<<Strike through>> == 'Full Row'`) mapped to the load list's **Deleted**
field, so struck-through rows are marked deleted in the Load List.

### Edits report for the file's owner

**Edits report .xlsx** (on an import's header; `POST
/api/mel/recipes/{id}/edits-report`, `mel/edits_report.py`) lists what the
import changes in its latest file, to give to whoever owns the file (the
mechanical engineer, for a MEL) so the next revision includes it:

- **Changed cells** (overrides): the row's key, the column (and its name in the
  file, when the import renamed it), the value in the file, the value used, the
  reason, and the row in the file.
- **Removed rows** (hidden rows): the key, the reason, the row in the file and
  its values as they are in the file.
- **Added rows** (custom rows): the key, the reason and the values entered.

An edit whose row isn't in the latest file is listed too, marked so. Each kind
of edit has a **Reason** box: in the override dialog, next to a hidden row on
the Rows tab, and in the custom row form. Reasons travel with the settings file.
The report includes unsaved edits. A revision keeps each row's position in the
file (rows are kept in key order), so the report and the import's row numbers
say where a row was; files uploaded before this have no row numbers.

When the next revision arrives and is uploaded, **Check edits…** (`POST
/api/mel/recipes/{id}/edits-check`) shows, for each edit, whether the file has
taken it in:

- a changed cell is **done** when the file now has the value the import uses
  (numbers compare as numbers: 11 = 11.0), and its row **gone** when the row
  isn't in the file;
- a removed row is **done** when the row isn't in the file any more;
- an added row is **done** when the file has the row with the same values, and
  **partly done** (naming the values that differ) when it has the row with
  others.

The done and gone ones change nothing any more and are ticked; **Clear** takes
the ticked edits out of the import, and **Save** keeps it. Edits still needed
stay, for the next report. The edits report's Status column says the same.

## Project lists

The key lists every project has, with fixed columns and rules
(`core/src/workbench_core/keylists/`, API
`desktop/engine/workbench_desktop/keylists_api.py`, UI `web/src/components/keylists/`).
You don't create or name them: each project has one of each.

- **Plant Areas**: a tree of the plant's breakdown. Each item has a
  **Tag number** (required, unique in the whole list), a **Description**
  (required, unique in the whole list), a **WBS number** (optional, but not used
  twice) and an **Area type**: WBS, Area, Building, Room or Panel. Uniqueness
  ignores case and extra spaces. Any type can sit under any other; a new item
  starts as the type below its parent's. The editor is the tree editor described
  below (expand/collapse, filter, drag and drop, Alt+arrow keys, Save/Discard),
  and saves are recorded in the change log.
- **Equipment Packages**: a flat list. Each row has a **Package number**
  (required, unique in the list), a **Description** (required, unique in the
  list), a **Vendor name** (optional; several packages can share a vendor) and a
  **Package type**: Vendor, Client, SWR Supplier, Valves, Instrumentation,
  Large Mech, Installer or Other. Rows keep the order you put them in and can be
  filtered.
- **Equipment Types** are the child rows of a package (**+ Type** on its row):
  a **Name** (required, unique across all packages) and an optional
  **Description**. Each type belongs to one package; its Package drop-down
  moves it to another. A package that has equipment types can't be deleted
  until they are moved or deleted. Types are saved together with the packages.
  - **Lists** on an equipment type opens its predefined rows for the
    **Cable Schedule**, **Equipment List**, **Instrument List** and **PLC I/O
    List**: the same four lists, columns, `<<tags>>` and grid as a load type's
    rows (one tab per list; the button shows how many rows it has). They are
    kept with the type and saved with the packages.
  - These are the rows the **Instrument generator** adds to the Project Master
    lists, once for each Instrument Runsheet row that names the equipment type,
    filled in from that row. The tags offered are the columns
    of the **Instrument Runsheet** (`<<STD>>`, `<<Area>>`, `<<MECH>>`, `<<SUF>>`,
    `<<PID>>`, `<<VIA_MB>>`, `<<CONF>>`, `<<Rack>>`, and `<<#1>>`, `<<#2>>`, … for
    as many numbers as the runsheet has).
  - **Export .xlsx / Import .xlsx** cover the packages and their equipment
    types together: the **Equipment Packages** sheet has one row per equipment
    type with its package's columns (Package number, Package description,
    Vendor, Package type, Equipment type, Equipment type description), and a
    package with no types has a row of its own. Each list's rows of the types
    are a further sheet ("Cable Schedule rows", ...) with an **Equipment type**
    column; a rows sheet left out of a file leaves those rows as they are. A
    workbook from before (a Packages sheet and an Equipment types sheet) still
    imports.
- **Load Types**: a flat list shown as a sortable, filterable grid; click a row
  (or **Add load type**) to edit it in a form, which saves straight away.
  **Code** and **Name** are required and unique; **kW or Amps**, **Voltage**
  (a whole number) and **Phases** (AC-3-phase, AC-3-phase+N, AC-1-phase-LN,
  AC-1-phase-LL, DC or DC-mA) are required. Optional: **From value** and
  **To value** (decimals, stored exactly; From must not exceed To), **STD Drg**,
  **Bucket type**, **Load type**, **Field options** (text), **Multi load**
  (yes/no) and **Load qty** (a whole number).
  **Clone** in a load type's form opens a new load type with its details, rows
  (as they are in the form) and PDF, coded `<code>-COPY` (then `-COPY2`…) and
  named "… (copy)"; it is saved with **Save**. On Equipment Packages, **⧉**
  duplicates an equipment type with its rows, as "… (copy)" straight after it
  in the same package; the list's **Save** keeps it.
  A load type can also have a **PDF** attached (one per load type, up to
  50 MB): attach, replace or remove it in the form, open it from the form or
  the grid's PDF column (it is shown in the app), or save a copy. The file is
  kept in the project folder (`keylists/load-types/`) and goes when its load
  type is deleted; attaching and removing are recorded in the change log.
- **Equipment Codes** and **Instrument Codes**: flat lists shown as a sortable,
  filterable grid; click a row (or **Add …**) to edit it in a form, which saves
  straight away. Both have a **Code** and **Name** (required and unique,
  ignoring case and extra spaces) and an optional **Description**. Equipment
  codes can have any number of **Disciplines** (E Electrical, I
  Instrumentation, M Mechanical, P Piping, C Civil, S Structural, H HVAC; the
  grid filters by one); instrument codes have an optional **PLC code** (free
  text, several codes may share one).
- **Motor Data** (`keylists/motors.py`): motors and their performance data. Every
  project starts with the **WEG W22 High Efficiency E3** range, 415 V 50 Hz,
  2, 4, 6 and 8 pole (145 motors, from the WEG W22 catalogue section 15, pages
  24 to 27, as printed; `keylists/motor_data_w22.py`): part number, poles,
  design (Standard, or High-Output in a special frame, marked * in the
  catalogue), kW, IEC frame, rated speed, full load current, locked rotor
  current, full load torque, locked rotor and breakdown torque, efficiency and
  power factor at 50/75/100 % load, sound pressure, moment of inertia, max.
  locked rotor times cold and hot, and weight. A grid with filters (poles,
  design…); a row is added or edited in a form; **Add missing WEG W22** adds back
  the catalogue motors that aren't there; Export/Import .xlsx and Reset (to the
  W22 range) like the other lists.

  A load is **matched to a motor** by its rating and the Load List's **Poles**
  field (a number an import can map): the smallest motor with those poles whose
  kW is at least the load's (a rating in HP is converted; Amps matches nothing),
  a Standard design before a High-Output one of the same kW. Template rows reach
  it as `<<Motor.PartNo>>`, `<<Motor.Frame>>`, `<<Motor.FLC>>`, `<<Motor.Eff100>>`,
  `<<Motor.PF100>>`… (`|default:` for a load with no motor), and calculated
  fields and the Load List Summary Page as the same names, e.g. input kW
  `<<rating>> / <<Motor.Eff100>> * 100`.
- **Drive Data** (`keylists/drives.py`): variable speed drives and their ratings.
  Every project starts with the **Rockwell PowerFlex 755TS** drives (297, from
  the PowerFlex 750TS-Series Technical Data, publication 750-TD104F-EN-P, pages 8
  to 21, as printed; `keylists/drive_data_755ts.py`): 200…240 V, 380…400 V, 480 V,
  575…600 V and 660…690 V, each in **Open** (IP00/IP20, Type Open), **IP54**
  (Type 12) and **Flange** mount (none at 690 V), with the catalog number, the
  **frame size**, and Normal Duty and Heavy Duty output amps (continuous, 1 min,
  3 s) and power (Hp at 240/480/600 V, kW at 400/690 V, both at 240 V; the 240 V
  drives' amps at 208 V too). Frame 6 and 7 drives are dual-voltage: listed at
  600 V and at 690 V with the same catalog number. Edited, exported, imported,
  reset and topped up (**Add missing PowerFlex 755TS**) like Motor Data.

  A load is **matched to a drive** of its voltage class (200…240 → 240, 380…415 →
  400, 440…480 → 480, 550…600 → 600, 660…690 → 690), its **Drive enclosure**
  (a Load List field: Open, IP54 or Flange; blank: Open) and its **Drive duty**
  (ND or HD; blank: Normal Duty): the smallest whose continuous amps at that duty
  (the 208 V figure for a 200…220 V load) cover the matched motor's FLC (a rating
  in Amps when there is no motor), or with no current, whose power covers the
  load's kW; the smaller frame of two the same. Reached as `<<Drive.CatNo>>`,
  `<<Drive.Frame>>`, `<<Drive.Amps>>` (at the load's duty), `<<Drive.kW>>`,
  `<<Drive.Duty>>`, `<<Drive.Enclosure>>`, `<<Drive.NDAmps>>`, `<<Drive.HDAmps>>`…
  in template rows, calculated fields and the summary page.
- **Starter Coordination** (`keylists/starters.py`): Type 2 coordinated direct on
  line starter selections by motor kW. Every project starts with **NHP's six Type 2
  coordination charts** (126 rows, from NHP TD-001-EN, pages 14 to 19, as printed;
  `keylists/starter_data_nhp.py`), at 400/415 V with Terasaki ZS earth leakage
  circuit breakers (AS/NZS 60947.4.1-2015):

  | Chart | Fault level | Contactor | Overload |
  |---|---|---|---|
  | ECH54.2 | 50 kA | Sprecher+Schuh CA7/CA9 | CEP7-1EF electronic |
  | ECH54.12 | 50 kA | Sprecher+Schuh CA7/CA9 | E300 (EtherNet/IP) |
  | RECH54.23 | 50 kA | Allen-Bradley 100-C/100-E | E300 (EtherNet/IP) |
  | ECH64.2 | 65 kA | Sprecher+Schuh CA7/CA9 | CEP7-1EF electronic |
  | ECH64.13 | 65 kA | Sprecher+Schuh CA7/CA9 | E300 (EtherNet/IP) |
  | RECH64.24 | 65 kA | Allen-Bradley 100-C/100-E | E300 (EtherNet/IP) |

  Each row has the chart, its fault level (kA), the motor kW and FLC, the circuit
  breaker (and its amps), the earth leakage setting range, the contactor, the
  overload relay and its setting range, the C/B instantaneous trip amps, the
  minimum trip as a multiple of FLC, and the chart's note (`*`: overload mounted
  separately or pass-thru; `^`: 75 kW kit with separate CTs). The list has a
  **project default chart** (ECH64.2, 65 kA, to start with). It is edited,
  exported (a "Settings" sheet holds the default chart), imported, reset and
  topped up (**Add missing NHP charts**) like Motor Data.

  Each **load type** has a **Starter chart**. Blank means the project default;
  **None** means no starter (a VSD, a feeder…). A load gets that chart's row for
  the smallest motor at least its kW (Hp is converted; a rating in Amps is
  matched on the chart's FLC; a load above 75 kW gets none). Reached as
  `<<Starter.CB>>`, `<<Starter.Contactor>>`, `<<Starter.Overload>>`,
  `<<Starter.Range>>`, `<<Starter.ELSetting>>`, `<<Starter.InstTrip>>`,
  `<<Starter.MinTrip>>`, `<<Starter.Chart>>`, `<<Starter.FaultkA>>`… in template
  rows, calculated fields and the summary page.
- **Electrical Equipment List** (EEL): equipment entered and edited here, in
  addition to any EEL import. A grid of every item; click a row (or **Add
  equipment**) for a form. **Tag number** (required, and unique across this list
  and every MEL / EEL import's rows), **Description**, **Equipment type** (an
  equipment code) and **Plant area** are required. Optional: **Vendor package**,
  **Load type** (choosing one copies its kW or Amps, voltage and phases),
  **Rating**, **kW or Amps**, **Voltage**, **Phases**, **Distribution panel**,
  **Supplied from** (Primary Supply or a panel of the Load List),
  **Manufacturer**, **Model number**, and **Supplied by / Installed by /
  Terminated by** (equipment packages).
  - Every item is also a Load List row (source "Electrical Equipment List"); its
    plant area, load type, panel and supply are set here and shown read-only
    there. Load List rows can be supplied from its panels. A deleted item's row
    stays in the Load List, marked deleted.
  - A panel can't stop being one (or be deleted) while rows are supplied from it
    by a person's or this list's choice, and supplies can't loop. Plant areas,
    load types, equipment codes and packages it uses can't be deleted.
  - A tag that an import gains later is marked ⚠ on the item.
- **Cable Types**: a flat list every project starts with a default set of (218
  types: power, flex, pilot, VSD, control, instrument pairs and triples, earth,
  fibre and Ethernet). Columns: **Code** (required, unique), **Application**
  (e.g. AC_415V), **Type** (e.g. Power), **Cores** (e.g. 3C+E), **Diameter**,
  **Voltage**, **Desc** and **Sort** (the list's order). A grid with a form, like
  Load Types; the form can make the code from the other fields. **Add missing
  defaults** puts back any default type that was deleted, without touching the
  rest.
- **PLC List**: a four-level tree of **PLC systems** (tag, description,
  manufacturer, model) → **racks** (tag number, unique in the project; plant
  area; rack type; first slot) → **cards** in slots (card type, name, spare,
  notes) → **IO points**, one per channel of the card type (tag, unique in the
  project when filled; description; spare; the signal comes from the card
  kind). Channels are numbered from 0 or from 1, as the card type's **First
  channel** says; changing it renumbers the points and keeps their tags. It replaces the PLC hardware register each generator
  had: the first time it is opened, the generators' registers are moved into
  it (each panel becomes a system, its racks are tagged `{PANEL}-R{n}`, and a
  rack's plant area is the one whose tag equals the panel's location). The
  card and rack types are edited here too. A card's type can't change to fewer
  channels while a channel it would lose has a tag or description. Export and
  import .xlsx (PLC cards, IO points, card types, rack types; an older
  generator workbook's PLC sheets can be imported too). A plant area with racks
  can't be deleted. A generator's **PLC hardware** tab now shows the PLC List's
  channels against its IO list build, read-only, with a link here.
- **Project Master Load List** (listed under **Project master lists**, first):
  the rows of every **MEL and EEL** import in the project,
  combined and always live (each import's latest file through its saved rules
  and mapping), with the mapped fields as read-only, sortable, filterable
  columns plus Status and Source. Each row's **Tag number** (the import's key
  when no tag is mapped) and **Description** come first, next to what is
  edited. Four columns are edited here and saved as soon
  as they are chosen: the row's **Plant area**, **Load type**, **Distribution
  panel** and **Supplied from**. **Set plant
  area… / Set load type…** give every row the filters show the same value.
  - Rows are remembered by import and key: a row that leaves its import (or
    whose import is deleted, or whose file marks it deleted) stays in the list,
    marked **Deleted**, with its allocations, and gets them back if it returns.
  - **Filled in automatically** (shown in italics): when a row's mapped area
    text equals exactly one plant area's tag number, or its load type text one
    load type's code (ignoring case and extra spaces). These follow the import
    until a person chooses a value, which is then never changed automatically.
  - A plant area or load type that a person allocated can't be deleted from its
    list until those rows are changed.
  - **Distribution panel** (a tick box) and **Supplied from** (Primary Supply,
    or one of the list's active distribution panels) are edited the same way;
    **Set supplied from…** sets it for every row the filters show. Filled in
    automatically from the import's mapped "is a load centre" and "supplied
    from" (a panel's tag), and kept once a person chooses. A row can't be
    supplied from itself, panels can't feed each other in a loop, and a panel
    can't stop being one while rows a person pointed at it are supplied from it.
  - Every allocation change is in the change log, with the row's tag.
- Plant Areas and Equipment Packages each keep their own unsaved draft when you
  switch between lists.
- A new project starts with empty lists; copying standards from another
  project does not copy them.
- **Export .xlsx / Import .xlsx** on every list
  (`keylists/workbooks.py`, API `/api/list-workbooks/{list}/export` and
  `/import`; the PLC List has its own workbook). The export is the saved list,
  one sheet per kind of row, with names instead of ids: a plant area by its tag
  number, a load type by its code, a package by its number.
  - **Import replaces the list with the file.** You first see what the file
    holds (how many rows are new, how many of the list are missing from it and
    would be removed, and anything that could not be matched); nothing changes
    until you confirm.
  - Rows are matched to the list by name (tag number, code, number) and keep
    their identity, so the Load List, the Electrical Equipment List and the
    deliverables still point at them. Renaming a row in the file makes it a new
    row.
  - A file goes through the same rules as a save in the app: a file with a
    duplicate, a missing required value, or without a row that is in use
    elsewhere is refused, and the list is left as it was.
  - **Load Types** has a sheet for the list and one for each deliverable list's
    rows; a rows sheet left out of the file leaves those rows as they are.
    Attached PDFs are not in the workbook and stay with their load types.
  - **Load List**: its rows come from the imports, so a file never adds or
    removes rows. Rows are matched by Source and Key, and only the plant area,
    load type, distribution panel, supplied from and cable columns are read
    (the Electrical Equipment List's rows: the cable columns only). Each changed
    row is in the change log; a change that breaks a rule is refused for that
    row and reported.
  - **Distribution Panels**: sheets Panels, Circuits (a row per pole) and
    Headings. A circuit names its load by tag.
- **Fields of the Project Master Load List** (`mel/load_fields.py`, API
  `GET/PUT /api/load-fields`): what List import maps a file's columns onto and
  what the Load List shows. **Edit fields…** on the Load List (or **Edit the
  Load List fields…** on an import's Mapping tab) renames, adds, deletes and
  reorders them for the project, and sets each one's kind (text, number or
  yes/no: how the import reads it). Save first shows what the change will do.
  - Every field has a key that never changes: it is what mappings, the rows'
    values and load types' `<<tags>>` use. A rename changes the name people
    see only, so nothing that uses the field has to change. A new field's key
    is made from its name (Motor HP → `<<motor_hp>>`).
  - A deleted field is taken out of every import's mapping, so its values stop
    coming through.
  - The fields the app reads (Tag, Description, Area, Equipment type,
    Quantity, Load units, Load rating, Voltage, Phases, Load type, Is a load
    centre, Supplied from, Deleted) can be renamed and moved, not deleted, and
    keep their kind.
  - The mapping sheet, the Load List's columns and its Excel export's
    reference columns all use the project's fields and names. The Load List
    deliverable's own columns are unchanged.
- **Calculated fields of the Load List** (`keylists/load_calcs.py`): a field
  of kind **calculated** is worked out for every row, like a spreadsheet
  formula referring to other cells of the row: active, reactive and apparent
  power, rated current, harmonic, utility and diversity factors, annual
  consumption and so on. **+ Add calculated field** in **Edit fields…**, then
  **ƒ Formula…**:
  - **Applies when**: a condition for the rows it is relevant to (blank: every
    row). Other rows get **Otherwise** (blank: nothing) and aren't checked.
  - **Formula**: one expression. `<<key>>` is a cell of the row: any Load List
    field (an import's value as it is, a number stays a number), another
    calculated field, the load's cable (`<<cable_length>>`, `<<cable_size>>`…)
    and what the app works out (`<<units>>`, `<<voltage>>` and `<<phases>>`
    fall back to the load type's; `<<loadtype>>`, `<<plantarea>>`,
    `<<suppliedfrom>>`…). **Insert a reference…** lists them all. The same
    functions and operators as List import's calculated columns, and `A if
    condition else B`. A blank cell is `''`: `(<<field>> or 0)` counts it as 0.
  - **Decimals**: a number answer is rounded.
  - **Checks on the answer**: expressions that hold for a good answer, with
    `<<value>>` the answer (e.g. `0 < <<value>> <= 1`), each an **error** or a
    **warning** with a message.
  - **▶ Try it on the Load List** works the unsaved formula out for every
    active row and lists the answers, problems first.

  Calculated fields are worked out in the order they use each other (a loop
  is refused), whenever the Load List is read. A formula that can't be worked
  out for a row (a blank or text where a number is needed, division by zero)
  leaves the cell blank with an error. In the Load List a calculated column is
  marked ƒ, and a cell with a problem ⛔ (error) or ⚠ (warning), with what is
  wrong as its tooltip. Calculated fields aren't import targets; they are
  columns of a Load List deliverable and `<<tags>>` for load types' rows, like
  any other field. A field a calculation uses can't be deleted.

  Example, with Power factor (`pf`) and Efficiency (`eff`) fields mapped from
  the MEL: Active power `<<load_rating>> * 0.746 / <<eff>> if <<units>> == 'HP'
  else <<load_rating>> / <<eff>>` (applies when `<<load_rating>> != ''`);
  Apparent power `<<active_power_kw>> / <<pf>>`; Reactive power
  `sqrt(<<apparent_power_kva>>**2 - <<active_power_kw>>**2)`; Rated current
  `<<apparent_power_kva>> * 1000 / (sqrt(3) * <<voltage>>)`; Annual
  consumption `<<active_power_kw>> * <<utility_factor>> * <<diversity_factor>> * 8760`.
- **Reset the Load List** (`POST /api/loadlist/reset`): a **Reset…** button on
  the Load List, and under the open project on the **Projects** page. A dialog
  asks what to reset and has to be confirmed before anything changes.
  - **Everything**: every remembered row is forgotten, with the plant areas,
    load types, panels, supplies and cable details people set and the rows kept
    as deleted. The list is built again from the imports.
  - **Only these**: the rows stay, and what is ticked is cleared on all of
    them: plant areas people chose, load types people chose, distribution
    panels and supplied from, cable details, rows kept as deleted.
  - Either way the MEL and EEL imports are read again afterwards, so what their
    latest files give is filled in automatically. The import files, rules and
    mappings are not touched, and rows of the Electrical Equipment List keep
    what that list sets (only their cable details can be cleared).
  - It can't be undone; the change log records the reset and how many rows it
    changed.
- **Enums** (`keylists/enums.py`, API `/api/enums`): the choice lists other
  lists pick from, edited per project in the **Enums** section. There are five,
  edited together and saved with Save:

  | Enum | A project starts with | Used by |
  |---|---|---|
  | Disciplines | E Electrical, I Instrumentation, M Mechanical, P Piping, C Civil, S Structural, H HVAC, PR Process, G General | Equipment Codes, Drawing List, Document List |
  | Drawing types | Single Line Diagram, Schematic, Termination Diagram, Loop Diagram, Block Diagram, Cable Block Diagram, Layout, General Arrangement, P&ID, Hook-up, Panel Schedule, Schedule, Index, Standard Detail, Datasheet, Other | Drawing List |
  | Document types | List, Schedule, Datasheet, Index, Register, Calculation, Specification, Report, Other | Document List |
  | Drawing statuses | Draft, IFR, IFA, IFT, IFC, AB, Superseded, Cancelled | Drawing List, Document List |
  | xProper | MCC, PLC, VSD, DOL, HMI, UPS, SCADA, RTD, I/O, P&ID, LV, MV, HV, AC, DC, MCB, MCCB, RCD, ELCB, CT, VT, ESD, JB, LCS, IP | Proper case: `<<…\|title>>`, `<<…\|proper>>`, `.title()`, `proper()` |

  - An item has a **code** and a **name**. A discipline needs a code; for the
    others it is optional, and an item is shown by its code when it has one.
    Codes are unique and names are unique within an enum. Items can be added,
    renamed, reordered and removed.
  - An item that a drawing, a document or an equipment code **uses can't be removed** (the
    count is shown beside it); renaming it is fine, and the lists follow.
    A discipline that equipment codes use keeps its code.
  - **Equipment Codes** tick their disciplines from this Disciplines enum.
  - **xProper** is a plain list of words (no codes). When text is put into
    proper case (`text_case.proper_case`), each word gets a capital first letter
    and the rest small. Then each xProper word is put back **exactly as written**
    wherever it appears with no letter either side, whatever its case: "mcc-01
    feed to plc i/o" becomes "MCC-01 Feed To PLC I/O". Digits next to a word are
    fine, so adding "kW" makes "7.5KW" into "7.5kW". This applies to the
    `title` / `proper` tag modifiers, `.title()` and `proper()` in expressions
    (MEL import rules, calculated fields, the summary page), using the
    project's own list.
- **Drawing List** (`keylists/drawing_list.py`, API `/api/drawing-list`): the
  project's register of drawings, as a sortable, filterable grid; click a row
  (or **Add drawing**) to edit it in a form, which saves straight away.

  | Field | Rule |
  |---|---|
  | Drawing number | required, unique |
  | Project name | text; a new drawing starts with the open project's name |
  | Title 1, Title 2, Title 3 | text |
  | Drawing discipline, Drawing type, Status | blank, or one of that enum's items (**fixed choices**) |
  | Revision | text |
  | Issue date | a date, or blank |
  | Vendor drg number, Vendor reference | text |
  | Equipment reference | one or more tags, separated by commas |
  | Scope | text |
  | Hyperlink | where the drawing is kept: a web address (`https://…`), or the path of a file or folder (`\\server\share\…`, `C:\…`) |

  - The **hyperlink** shows in the grid as a link that opens in a new window
    (clicking it does not open the form); the form has **Open** and **Copy**
    beside it. Only web addresses, `file://` addresses and paths are accepted,
    so a link is safe to open. A web address opens in the browser; opening a
    file path depends on what the browser or desktop shell allows, which is
    what Copy is for.
  - A tag of the **equipment reference** that is in neither the MEL nor the
    Electrical Equipment List is **flagged** (⚠ on the row, and after saving),
    but never stops a save.
  - Export .xlsx / Import .xlsx: one sheet with these headings. On import a
    drawing keeps its identity by its number; a discipline, type or status is
    read by its code or its name, and one that is not in the Enums refuses the
    file, naming the drawing. Dates are read as `dd/mm/yyyy`, `yyyy-mm-dd` or
    an Excel date.
- **Document List** (API `/api/document-list`): the project's register of
  documents: its lists, schedules, datasheets and the like. It is the Drawing List with
  **one Title** in place of the three: Document number (required, unique),
  Project name, Title, Document discipline, Document type, Revision, Status,
  Issue date, Vendor doc number, Vendor reference, Equipment reference, Scope
  and Hyperlink, with the same grid and form, the same rules, and the same
  Excel export and import. Its type is picked from the **Document types** enum;
  discipline and status are the ones the drawings use.
- **Instrument Runsheet** (`keylists/instrument_runsheet.py`, API
  `/api/instrument-runsheet`): what the **Instrument generator** will run from
  (see [Deliverable generators](#deliverable-generators)).
  One row is one instrument assembly, edited in a spreadsheet grid that takes
  rows pasted from Excel.

  | Column | Tag | Rule |
  |---|---|---|
  | Equipment Type Ref | `<<STD>>` | required; the name of an Equipment Type |
  | Area Ref | `<<Area>>` | required; a Plant Area's tag number |
  | Parent Equipment Ref | `<<MECH>>` | required; a tag in the Electrical Equipment List or the MEL |
  | Name Suffix | `<<SUF>>` | text |
  | PID | `<<PID>>` | text |
  | IO via MARSHALLING BOX | `<<VIA_MB>>` | text |
  | Confirmed | `<<CONF>>` | TRUE or FALSE (blank is FALSE) |
  | PLC Rack Num | `<<Rack>>` | text |
  | #1, #2, … | `<<#1>>`, `<<#2>>`, … | text, kept exactly as typed |

  - The three references **must match for the list to be saved** (ignoring
    case and extra spaces). A cell that matches nothing is marked as you type,
    with the reason, and Save stays off until it is fixed.
  - The equipment type and the area are kept by identity: renaming one changes
    nothing here, and one that a row uses can't be deleted. The parent is kept
    as its tag.
  - The **number columns are not fixed at 35**. The grid starts with #1 to #35;
    **+ 5 # columns** adds more, and so does pasting rows that are wider. Once
    saved, the list has as many number columns as its widest row uses (35 at
    least, 500 at most), and `<<#36>>`, `<<#37>>`, … are offered as tags.
  - Rows may repeat and keep their order. A row with nothing in it is dropped.
  - The tags are what an **equipment type's rows** (its **Lists**) are filled in
    with, so that is the set its tag picker offers.
  - Export .xlsx / Import .xlsx: one sheet with these headings (as many # columns
    as the list has; a file may have more). An import
    replaces the rows and goes through the same must-match rule.
- **MEL** (`GET /api/mel-list`): every row of the latest file of every **MEL
  import**, with its columns as the import's column rules leave them. It is
  **read only**: it changes when a file is uploaded or an import's rules change,
  in List import. Rows unticked there as not loads are in it too, marked *not a
  load*: they are not in the Load List, but the Instrument Runsheet's Parent
  Equipment Ref can name that equipment (a chute, a bin, a conveyor). It can be
  exported to Excel, not imported.
- **Distribution Panels**: the schedule of each distribution board, three-phase
  or single-phase, shown as the switchboard or as a single line diagram. Its
  circuits are the Load List rows supplied from the panel. See
  [Distribution panel schedules](#distribution-panel-schedules).

## Lists, trees & tables

> The **Lists & tables** tab has been removed from the app. The engine still has
> this reference data and its API (and copying a project's standards still
> copies it), but there is no screen to edit it, the dashboard doesn't show it,
> and the sample data no longer adds any. What follows describes the engine.

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

## Deliverables

The lists a project issues, in the **Deliverables** section
(`core/src/workbench_core/deliverables.py`, API
`desktop/engine/workbench_desktop/deliverables_api.py`, UI
`web/src/components/deliverables/`).

- A deliverable is a **Cable Schedule**, **Instrument List**, **PLC I/O List**,
  **Equipment List**, **Load List** or **Distribution Panel**, with a name (unique), document number and
  title. A project can have several of each type.
- A **Distribution Panel** deliverable is the schedule of one panel of the
  Distribution Panels list (see below). Every other type's content comes from
  the **Project Load List** (see below) or from a
  **generator** build, optionally only the rows where one column is one of a
  list of values (for example one area).
- **Issue Rev A / B / C…** (then AA, AB…) freezes the content of the generator's
  latest build, or of an earlier build you pick, with the date, who issued it and
  a description. Issuing never builds: you issue a build you have seen. The
  panel above the revisions shows what a new revision would contain and what has
  changed since the last one, and warns when the generator has changed since its
  latest build.
- Each revision keeps its rows and the changes against the revision before it
  (added, removed, changed, old → new per column). View either at any time, and
  export a revision to Excel or CSV; the document number, revision letter and
  title name the file.
- Issued revisions can't be edited; only the description can be amended. The
  **latest** revision can be **withdrawn** with a reason: its frozen copy is
  deleted, the letter is used by the next issue, and the change log records it.
- A deliverable with revisions can't be deleted, and a generator that feeds a
  deliverable can't be deleted. Deleting a generator's builds does not affect
  issued revisions.

### Generated from the Project Load List (Load Types as templates)

The power side of a project needs no generator workbook. The Load List is the
runsheet and the **Load Types** are the templates
(`core/src/workbench_core/keylists/loadgen.py`):

- Each load type has predefined **rows for each list**: Cable Schedule, Equipment
  List, Instrument List and PLC I/O List (the tabs of the load type's dialog; the
  grid takes paste from Excel).
- Every active load in the Load List adds the rows of its allocated load type,
  in tag order, with the `<<tags>>` in the cells replaced by that load's data.
  A deliverable of type Load List has one row per load and needs no template rows.
- The content is generated on the spot whenever you look at the deliverable, so
  there is nothing to build; **issuing** freezes it as the next revision.
- A load with **no load type** blocks issuing (the message names the loads). A
  tag that matches nothing is left in the text and reported as a warning.

| List | Columns |
|---|---|
| Cable Schedule | Cable Number, From, From Description, To, To Description, Cable Type, Cable Code, Cores, Size, Voltage, Length (m), Route, Remarks |
| Equipment List | Tag, Description, Equipment Type, Plant Area, Rating, Units, Voltage, Phases, Supplied From, Manufacturer, Model, Remarks |
| Instrument List | Tag, Description, Instrument Type, Plant Area, Service, Signal, IO Type, Range, Units, Remarks |
| PLC I/O List | Tag, Description, Signal, IO Type, PLC System, Rack, Slot, Channel, Plant Area, Remarks |
| Load List | Tag, Description, Plant Area, Load Type, Rating, Units, Voltage, Phases, Supplied From, Distribution Panel |

Tags (not case-sensitive; type `<<` in a cell to pick one):

| Tag | Filled with |
|---|---|
| `<<Tag>>`, `<<Description>>`, `<<Area>>`, `<<Rating>>`, `<<EquipType>>`, `<<Qty>>` | the load's own data from the import or the Electrical Equipment List |
| `<<Units>>`, `<<Voltage>>`, `<<Phases>>` | the load's value, else the load type's |
| `<<PlantArea>>`, `<<PlantAreaDesc>>` | the allocated plant area |
| `<<LoadType>>`, `<<LoadTypeName>>`, `<<StdDrg>>`, `<<BucketType>>` | the allocated load type |
| `<<SuppliedFrom>>`, `<<SuppliedFromDesc>>` | the panel it is supplied from, or Primary Supply |
| `<<Row>>` | 1, 2, … within the load's rows of that list |
| `<<CableCode>>`, `<<CableDesc>>`, `<<CableCores>>`, `<<CableVoltage>>` | the cable found in Cable Types for the load |
| `<<CableSize>>`, `<<CableInsulation>>`, `<<CableLength>>`, `<<CableParallel>>`, `<<CableConstruction>>` | the load's cable details from the Load List |
| `<<CableNo>>`, `<<Phase>>` | 1, 2, … and L1 / L2 / L3 / N / E for each cable of a "Per power cable" row |
| any mapped load-list field, e.g. `<<starter_type>>` | that field of the load |

### Component tables of a load type

A load type's **Components** tab holds tables of parts that depend on the load
(`ComponentTable` on `LoadType`): one per kind of component, such as a **CB**
or a **Contactor** table. A table is **matched on** a load field: the Load
rating by default, or any number or calculated field of the Load List (Rated
current…) or the load's voltage, quantity, cable length or size. Its rows are a
**Min** and **Max**, then its own columns (Part Number, Manufacturer,
Description… by default). A load gets the first row whose Min ≤ its value ≤ Max
(a blank bound is open-ended, so 7.5 with rows 0–7.5 and 7.5– gets the first).

Template rows reach the row as `<<LoadType.CB.PartNumber>>` (the table, then
a column; spaces in names can be left out; `<<LoadType.CB>>` is its first
column, `.Min` / `.Max` its range). A load with no value there, or one no row
fits, gets blank (`|default:TBA` fills it); a table or column that doesn't
exist is reported as a tag that matches nothing. Typing `<<LoadType.CB.`
offers the table's columns. Tables are copied by **Clone**, kept by the Load
Types workbook import, and are "Table <name>" sheets of the load type's own
workbook (**Export rows .xlsx**), whose first two headings are "Min <field>"
and "Max <field>".

### One type's rows as a workbook

A load type's rows (in its form) and an equipment type's (in its **Lists**)
have **Export rows .xlsx** and **Import rows…**
(`POST /api/list-workbooks/type-rows/export` and `.../import`). The workbook,
named after the type ("DOL rows.xlsx"), has a sheet per list (**Cable
Schedule**, **Equipment List**, **Instrument List**, **PLC I-O List**) with
the project's columns of that master list (and **Repeat** on the Cable
Schedule), and a **Tags** sheet listing what a cell can use: the row's tags,
the linked records' dotted tags and the modifiers. The export is the rows as
they are in the editor, saved or not. An import is checked as a save is (a
heading that is no column of the list, or a bad Repeat, is refused) and shows
how many rows each list has; **Replace rows** puts them in the editor, in
place of those lists' rows (a list without a sheet stays as it is, the Tags
sheet is ignored), and **Save** keeps them.

### Tags in template rows: dot notation and modifiers

A cell of a load type's or an equipment type's rows can hold
`<<path|modifier|modifier:arg>>` (`keylists/tag_paths.py`).

- **path**: one name as before (`<<Tag>>`, `<<LoadTypeName>>`, `<<load_rating>>`,
  `<<#1>>`, `<<STD>>`, the cable tags), or names joined by dots that follow the
  row's links to other records and end on one of their fields. Names ignore case,
  spaces and `_`. A path that ends on a record gives its name (a load's tag, a
  load type's code, a plant area's tag…).

  | From | Links | Example |
  |---|---|---|
  | a load (Power) | `LoadType`, `PlantArea`, `SuppliedFrom` (a load), `Eel` (its Electrical Equipment List item), `Cable` (the matched Cable Types row, per-cable rows) | `<<SuppliedFrom.LoadType.Code>>` |
  | a runsheet row (Instrument) | `EquipmentType` (→ `Package`), `PlantArea`, `Parent` (the load its parent tag names), `Rack` (the PLC List rack, → `System`, `PlantArea`) | `<<Parent.PlantArea.Parent.Tag>>` |
  | a plant area | `Parent` | `<<PlantArea.Parent.Parent.Tag>>` |
  | an Equipment List item | `EquipmentCode`, `VendorPackage`, `SuppliedBy`, `InstalledBy`, `TerminatedBy`, `PlantArea`, `LoadType`, `Load` | `<<Eel.EquipmentCode.Name>>` |

  A load's fields are every Load List field (by tag or name, calculated ones
  too), its tags and its cable details; the other records' fields are listed in
  the editor's **All tags ⓘ** panel.
- **modifiers**, left to right: `upper`, `lower`, `title` (or `proper`: Each
  Word, keeping the Enums' xProper words such as MCC and PLC), `trim`, `nohyphen`,
  `int` (cut off), `round:n`, `dec:n` (always n decimals, kept as text),
  `pad:n` (zero-pad, kept as text), `left:n`, `right:n`, `replace:a:b` (`\:`
  for a colon), `prefix:x` / `suffix:x` (only when not blank), `default:x`
  (when blank). E.g. `<<LoadType.Name|upper>>`, `<<#1|int|pad:3>>`,
  `<<EquipmentType.Package.Vendor|default:TBA>>`.
- A link the row doesn't have (no load type allocated, no parent found) gives
  blank. A name that isn't a link or field, or an unknown modifier, leaves the
  tag as typed and is listed with what is wrong in the master list's warning.
- In the rows grid, typing `<<` offers the tags, a `.` after a link offers that
  record's fields, and `|` offers the modifiers.

### Cables: the load's details pick the cable from Cable Types

Cable sizing is done outside the app. Each load in the **Load List** has a
**Cable** cell (click it, or **Set cable details…** for every row the filters
show) with: power cable **Multicore / Single core**, **parallel cables**, **core
size**, **insulation**, **earth cable size** (single core only) and **cable
length**. Sizes and insulations are the ones in the Cable Types list, which has
an **Insulation** column for this (filled from the descriptions of the default
cables, and of lists saved before the column existed).

In a load type's Cable Schedule rows, the **Repeat** setting makes a row
**Per power cable**. Such a row is written once for each cable:

- multicore: one row per parallel cable (1 × 70 mm² is one row, 2 × 50 mm² two);
- single core: per parallel set, one row per conductor (L1 L2 L3, plus N for
  3-phase+N; L N, L1 L2 or + − otherwise) with cores `1C`, then one earth cable
  row (Earth, 1C, the earth size).

The cable is the Cable Types row whose **type** is the row's Cable Type cell
(Power, VSD, Power Flex…), whose **cores** are the row's Cores cell (`1C` for
single core), and whose **size** and **insulation** are the load's. If several
match, the one whose application names the load's voltage (`AC_415V`) is used.
The row's Cable Type, Cable Code and Cores cells show what was found. A load
type can have several repeating rows (for example supply and motor cables of a
VSD). A row without Repeat can still use the cable tags: it gets one cable.

When the details are missing or nothing in the table matches, the row is still
written with the cable cells blank and the deliverable shows a warning naming
the loads; it can still be issued.

### Distribution panel schedules

The **Distribution Panels** project list (`keylists/distribution_panels.py`,
`keylists/panel_calc.py`, API `/api/distribution-panels`, UI
`DistributionPanelsEditor.vue`) holds the schedule of each distribution board.

- A panel is **three-phase** or **single-phase** and has an even number of
  **ways**: odd ways down the left of the chassis, even ways down the right. On
  a three-phase panel each way has a **red, white and blue** row (circuits QR1,
  QW1, QB1); on a single-phase panel a way is one row (Q1).
- A panel is linked to a **distribution panel of the Load List**. Every active
  load supplied from that row is a circuit to place; **Place all** puts the ones
  not yet on a way on the first free ways (a three-phase load takes a way's three
  rows). A panel can also be left unlinked, with a typed tag and typed circuits.
- A circuit can instead be a **spare circuit breaker**, an **RCD RTS**, a
  **lighting control circuit** or anything else typed in. A row with nothing on
  it is a **spare space**. A **heading** (for example "Lighting Contactor")
  runs across the schedule above a pair of ways.
- What the Load List doesn't hold is typed on the schedule, a row for each
  pole: the **CB rating**, a **quantity** and the **watts each**. Left blank,
  the quantity is 1 and the watts come from the load's rating (a kW rating is
  shared equally by its poles; an Amps rating is amps x voltage x power factor
  on each pole).
- Each panel is shown as the **Switchboard** (the two-sided schedule) or as a
  **Single line diagram** drawn from it: the supply, upstream CB and isolator,
  the busbar, and a breaker and label for each circuit.
- A load that is deleted or moved to another panel in the Load List stays on
  the schedule, marked, until it is removed. Nothing in the Load List is changed
  from here.

The header figures, from the single-phase voltage, one power factor for the
panel and the isolator and chassis rating:

| Figure | How it is worked out |
|---|---|
| kVA per phase | watts on the phase / power factor / 1000 |
| Amps per phase | kVA x 1000 / single-phase voltage |
| Maximum Amp | the largest phase amps |
| 3PH kW | all the watts / 1000 |
| Remaining Capacity (Amps), % | rating - Maximum Amp, and that as a share of the rating |
| Maximum kVA Rating | 3 x voltage x rating / 1000 (single-phase: voltage x rating / 1000) |

There is no diversity factor, and line-to-line (two-pole) loads are counted on
one phase only.

Issued as a deliverable, the schedule is one row per pole row, spare spaces
included, with the columns **Circuit, Way, Phase, Side, Section, Tag,
Description, Load Type, Qty, Watts (Ea.), Total W, CB Rating (A)**; revisions
are compared by Circuit. The header figures are frozen with each revision and
go on a second sheet, **Panel**, of the Excel export. A panel that a deliverable
issues can't be deleted.

### Sample data

**Load sample data** on the Dashboard (`POST /api/sample-data`) fills every list
that is still empty with a small invented plant: plant areas, equipment packages
and types, equipment and instrument codes, four load types with rows for every
list, three switchboards in the Electrical Equipment List, a PLC, a MEL import
of nine loads, the schedule of
MCC-2 in Distribution Panels, three rows in the Instrument Runsheet, four
drawings in the Drawing List, three documents in the Document List, and one
deliverable of each type. Lists that already have data are left
alone, so it is safe to run on a project in use.

## Deliverable generators

There are two generators, both built into the app (generators are no longer
made by importing a workbook), and both fill the same four **Project Master
lists** (`keylists/master.py`, API `/api/master`):

| Master list | Deliverable type made from it |
|---|---|
| Project Master Cable Schedule | Cable Schedule |
| Project Master Equipment List | Equipment List |
| Project Master Instrument List | Instrument List |
| Project Master IO List | PLC I/O List |

- **Power**: every load of the Project Load List adds the rows its load type has
  for each list (see
  [Generated from the Project Load List](#generated-from-the-project-load-list-load-types-as-templates)).
- **Instrument**: every row of the **Instrument Runsheet** adds the rows its
  **equipment type** has for each list, with the tags (`<<STD>>`, `<<MECH>>`,
  `<<#1>>` …) filled in from the runsheet row. A number the row doesn't have
  fills in as nothing; text such as `**CV**-CPL1` is written as typed.
- A master list is **worked out when it is opened**, so it is always up to date
  and there is nothing to run. It is **read only**: to change a row, change the
  Load List, Load Types, Equipment Packages or Instrument Runsheet.
- Besides the list's own columns each row has **Generator** (Power or
  Instrument) and **Confirmed** (the runsheet row's; a load's rows are always
  TRUE). Unconfirmed runsheet rows are in the master lists, marked FALSE.
- **Each project has its own columns** (`keylists/master_columns.py`, API
  `GET/PUT /api/master-columns`). **Edit columns…** on a master list renames,
  adds, deletes and reorders the columns of all four; Generator and Confirmed
  always come last. Save first shows what the change will do (`?dry_run=true`),
  then makes it in one go:
  - a **rename** moves the cells of load type and equipment type rows to the
    new name, and renames the column in the column choices and filters of the
    deliverables made from the list;
  - a **delete** drops those cells and takes the column out of those
    deliverables (a filter on it is cleared);
  - the row editors, the Load Types and Equipment Packages workbooks and the
    deliverables' column choices all use the project's columns.

  Some columns can be moved but not renamed or deleted: **Tag** (**Cable
  Number** on the Cable Schedule), which revisions are compared by, and the
  Cable Schedule's **Cable Type**, **Cores** and **Cable Code**, which "Per
  power cable" rows fill in. Generator, Confirmed and Repeat can't be used as
  names. Issued revisions keep the columns they were issued with, so the first
  revision after a rename shows the old column removed and the new one added.
  The Load List and Distribution Panel columns are fixed.
- The masters are under **Project master lists** in Project lists, each with
  filters and Excel / CSV export of the list as it is now. The Generators
  section shows, for each generator, how many rows it adds to each master
  (`GET /api/generators/types`).

**Load List Summary Page** (under Project master lists; `keylists/load_summary.py`,
`/api/load-summary`): tables that total up the Load List, worked out from it
whenever they are shown (and exported as a sheet per table with **Export
.xlsx**). **Edit tables** to add or change them, **▶ Preview** to work out
the edited tables without saving, then **Save**. A table has:

- a **filter**: which active loads it looks at (blank: all), e.g.
  `not <<ispanel>> and <<loadtype>> != 'SPARE'`;
- **rows**, each typed in: a name, a condition choosing its loads among the
  filtered ones, and optionally a **reference load** (a tag) whose own values
  its formulas can use as `<<Ref.load_rating>>`. A load's `<<supplychain>>`
  lists the panels it is fed from, nearest first, so
  `'TX-1' in <<supplychain>>` is every load fed from TX-1 directly or through
  the MCCs below it, which is a transformer's loading; `<<suppliedfrom>> ==
  'MCC-1'` is an MCC's own loads;
- **columns**, in order: a **total of a field** (Sum, Count, Min, Max or
  Average of any Load List field, calculated ones too, or the rating,
  voltage, quantity or cable length, over the row's loads for which the
  column's own condition holds; blanks and text are left out) or a
  **formula** over the row's other columns by name (`<<Total kW>>`),
  `<<Row>>`, `<<Loads>>` and `<<Ref.field>>`, with Applies when, Otherwise,
  decimals and error/warning checks like a calculated field;
- an optional **Total** row, over every load the filter lets in.

The Loads column says how many loads a row has (hover for their tags). A
cell whose formula can't be worked out, or that fails a check, is marked ⛔
or ⚠. `<<ispanel>>` and `<<supplychain>>` can be used in the Load List's
calculated fields too.

**Deliverables are made from a master list.** A deliverable of one of the four
types takes its rows from its master through:

- a **filter** (only the rows where one column is one of a list of values, for
  example Confirmed is TRUE, or Plant Area is 100);
- a choice and **order of columns** (**Choose and order…**; the column revisions
  are compared by, Tag or Cable Number, has to stay).

It follows the master until a revision is issued, which freezes exactly those
rows and columns; revisions, comparison, withdrawal and export work as before.
A **Load List** deliverable is still made from the Project Master Load List, and a
**Distribution Panel** from its panel; both can choose and order columns too.

A **Load List** deliverable's content is the whole Project Master Load List:
its own ten columns (Tag … Distribution Panel), the load's power cable
(Cable Length (m), Power Cable, Parallel Cables, Cable Insulation, Cable Size,
Earth Size), then each of the project's Load List fields besides Tag and
Description, by its name (a name the list already has gets " (import)", e.g.
Voltage (import)). **Choose and order…** picks from all of them; Tag has to
stay. Renaming or deleting a Load List field renames it in, or takes it out of,
the column choices and filters of Load List deliverables. A Load List
deliverable made before this, showing every column, was given the ten columns
it had, so its next revision is unchanged until its columns are chosen again.

A project that has generators from **imported workbooks** (made in an earlier
version) keeps them, listed under the two types: they can still be opened,
edited in spreadsheet-style grids, checked, built, compared with the previous
build, exported and deleted, and deliverables that use them keep working. The
engine (`core/src/workbench_core/generators`) still reads a generator workbook
from its command line (`python -m workbench_core.generators
import|check|build|diff|export|golden`) and API; only the app's import is gone.
See [docs/GENERATORS.md](docs/GENERATORS.md).

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
- Closing the window leaves no `workbench-engine.exe` in Task Manager. (The app ends the engine's whole process
  tree when it closes, and the engine also stops itself if the app is killed. An engine left over from a
  build before this was fixed has to be ended in Task Manager once.)
  (The engine also watches the shell's PID and exits if the shell dies.)
- If the engine never connects, check `%TEMP%\workbench-engine.log`.
- Symbol detection: the **OCR** status is shown in a library's *Settings*. Windows OCR needs an OCR-capable display language (Settings > Time &
  language); on a scanned sheet, a missing language shows as a page warning.
