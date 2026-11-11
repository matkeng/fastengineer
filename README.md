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
- **Project lists**: the key lists every project has: Plant Areas, Equipment
  Packages, Load Types, Equipment Codes, Instrument Codes and the Load List
  (see below).
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
   - a **text scan** option, which finds tags anywhere in the page text, as one word or as
     two words stacked as in a bubble;
   - the threshold for new templates, when to use OCR, and **ignored text** (words, and areas
     such as the title block, drawn once).

   Leave the pattern blank to take template tags exactly as written. Libraries can be
   created, copied, exported and imported as JSON.
2. **Add PDFs** into a library. Each page is rendered once at 200 DPI to a lossless PNG,
   with the page's rotation applied, and its text-layer words are mapped into the same pixel
   frame (`<data dir>/symbols/<drawing>/`).
3. **Templates.** Press **Draw on a drawing** in the sidebar (or **New template** on any
   page) and drag a box around a symbol. Adjust the box with its handles; a preview shows
   the template that will be cut (page text erased, trimmed to the linework, outlined in
   green on the sheet) and its size before you create it. You can also add a symbol image
   file. In the template editor:
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

## Project lists

The key lists every project has, with fixed columns and rules
(`core/src/workbench_core/keylists/`, API
`desktop/engine/workbench_desktop/keylists_api.py`, UI `web/src/components/keylists/`).
Unlike **Lists & tables**, you don't create or name them: each project has one of each.

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
- **Load Types**: a flat list shown as a sortable, filterable grid; click a row
  (or **Add load type**) to edit it in a form, which saves straight away.
  **Code** and **Name** are required and unique; **kW or Amps**, **Voltage**
  (a whole number) and **Phases** (AC-3-phase, AC-3-phase+N, AC-1-phase-LN,
  AC-1-phase-LL, DC or DC-mA) are required. Optional: **From value** and
  **To value** (decimals, stored exactly; From must not exceed To), **STD Drg**,
  **Bucket type**, **Load type**, **Field options** (text), **Multi load**
  (yes/no) and **Load qty** (a whole number).
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
- **Load List**: the rows of every **MEL and EEL** import in the project,
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
- **Distribution Panels**: the schedule of each distribution board, three-phase
  or single-phase, shown as the switchboard or as a single line diagram. Its
  circuits are the Load List rows supplied from the panel. See
  [Distribution panel schedules](#distribution-panel-schedules).

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
of nine loads, a list, tree and table under Lists & tables, the schedule of
MCC-2 in Distribution Panels, and one deliverable of each type. Lists that already have data are left
alone, so it is safe to run on a project in use.

## Deliverable generators

> Imported generator workbooks are being **retired** for the power side: Load
> Types and the Load List now generate the same deliverables inside the app (see
> above). Generators keep working and remain the route for the instrument side
> until that moves across too.


The **Generators** section imports a generator workbook (cable schedules, device list, IO list).
You edit its runsheet and templates in spreadsheet-style grids, with paste from Excel, and preview a run.
Then you check, build, see what changed since the previous build, and export the schedule.
The engine (`core/src/workbench_core/generators`) reproduces the Excel/VBA generator workbooks cell for cell.
It also has a command line (`python -m workbench_core.generators import|check|build|diff|export|golden`).
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
