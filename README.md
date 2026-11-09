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
