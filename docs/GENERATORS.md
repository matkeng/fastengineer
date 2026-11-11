# Deliverable generators

> **Being retired.** For the power side, deliverables are now generated from the project's own
> lists: each Load Type holds template rows per list and the Project Load List is the runsheet
> (`workbench_core.keylists.loadgen`; see "Generated from the Project Load List" in the README).
> Imported generator workbooks still work and are still the route for the instrument side.

`workbench_core.generators` re-implements the Excel/VBA generator workbooks: cable schedules,
an instrument device list and a PLC IO list. It is a pure Python engine. It takes a runsheet
(one row per run) and template blocks of `<<TAG>>` cells, and produces the output schedule
cell for cell, in **compatibility mode**.

| Module | What it does |
|---|---|
| `models.py` | Generator, config, runsheet, templates, computed columns, build result |
| `text.py` | value to text (VBA `CStr`), case-insensitive literal replace, space collapse, "as typed" cell reading |
| `expr.py` | safe expression language for late formulas (`F=<<LEN2>>*<<QTY>>`): Excel precedence, no `eval` |
| `computed.py` | computed columns that replace template formulas: `concat`, `exists`, `lookup`, `expr`, `count` |
| `expand.py` | `build()`: tag discovery, run selection, expansion, derived tags, locked runs, freeze-and-expand, output assembly |
| `check.py` | `check()`: rules C1-C20 and the template index |
| `diff.py` | change report keyed on DiffKey (`key`, `key#2`, ...), columns matched by name |
| `xlsx_import.py` | imports a generator workbook; maps the known template formulas to computed columns, flags the rest, reports data issues |
| `xlsx_export.py` | `.xlsx` ("Schedule", bold frozen filtered header, document properties) and `.csv` |
| `golden.py` | golden tests against real workbooks kept outside the repository |

## In the app (Generators section)

A build becomes an issued document in the **Deliverables** section: a deliverable points at a
generator and freezes one of its builds as Rev A, B, C… (see the README's Deliverables section).

1. **Import** a generator workbook (`.xlsx` / `.xlsm`) with "Import workbook…", by dropping it on the page, or with "Use the sample generator".
   The import report lists what was read, which formulas became calculated columns, and any data issues.
2. **Runsheet** (an editable grid, one row per run): the header shows each column's label and `<<TAG>>`.
   - Keys work like this:
     - the key column offers the template IDs;
     - a key with no template is highlighted;
     - blank, `nr` or `none` skips the run.
   - Editing works like a spreadsheet:
     - type to edit, then Enter, Tab or the arrow keys to move;
     - Ctrl+C / Ctrl+V copy and paste with Excel (tab-separated, quoted multi-line cells included);
     - Delete clears the selected cells;
     - **+ Row** gives the new run the next run number.
   - The locked column is a tick box.
   - Columns calculated in the workbook (`calc`) are read-only.
3. **Templates**: a block list (rows, runs using it, duplicate-ID warning) and the selected block's rows in the same grid.
   - Typing `<<` suggests the runsheet tags, their `_S` / `_P` forms, derived tags and `<<PARENT>>`.
   - `ƒ calc` columns are calculated (join, lookup, existence check) and read-only.
   - The **preview** expands the block for a chosen run, including unsaved edits. Hover a value to see its template text.
4. **Check** runs rules C1-C20 on the current edits. Clicking a finding opens the runsheet row or template.
5. **Build** saves the edits, then builds from **From run** to **Run below** (exclusive).
   - Every build is kept.
   - It shows the stats and warnings, the output and the **changes** against the previous build (added / removed / changed, old → new per column).
   - Click an output row to see the run and template row it came from.
   - **Export .xlsx / .csv** writes the shown build (Save As in the desktop app).
6. **PLC hardware**: the PLC panels of the project, each with racks, each with cards in numbered slots.
   - **Card & rack types** is a catalogue shared by every generator.
     - It starts with Network plus DI, DO, AI, AO and RTD cards in 8, 12, 16 and 32 channel variants, and one modular rack type.
     - Fill in part numbers and descriptions; a rack type can have a maximum slot count.
     - Types used in a saved rack can't be removed.
   - **Panels, racks & cards**:
     - add a panel (tag, description, location);
     - add racks (rack number, type, first slot number); each new rack starts with a network adapter;
     - fill slots with cards: click an empty slot or use + Card.
     - A selected card can change type or name (default `{PANEL}-R{rack}-S{slot}`), be marked spare, or be moved, removed, or given an empty slot before it.
   - **Live checks:**
     - duplicate panel tags, rack numbers or card names;
     - unknown types;
     - more cards than the rack's slots;
     - a rack with IO but no network adapter.
   - **Totals:** cards and channels per kind, and channels against the latest IO list build. The IO list's card type column is matched to the card part numbers.
   - **Export .xlsx:** the card schedule.

   IO points are not assigned to channels yet; that is the next step.
7. **Export inputs / Import inputs…** (generator header): bulk editing in Excel.
   - **Export inputs** writes every input table to one workbook, one sheet per table:
     - RunSheet (labels row, tags row, then one row per run; column A is the run's Row ID);
     - Templates (calculated cells show as `ƒ kind`);
     - Parents, Derived tags, Routes, Cable prefixes;
     - PLC cards (one row per card; the card type can be its ID, part number or e.g. `DI16`);
     - Card types, Rack types;
     - one `T <name>` sheet per lookup table.

     An About sheet explains the layout.
   - **Import inputs…** reads the edited workbook and shows, per sheet, the rows added, removed and changed (old → new per column), plus any errors. Tick the sheets to apply; nothing is saved before Apply.
   - Sheets deleted from the workbook, or not ticked, are left unchanged. Sheets with errors can't be applied.
   - Card and rack types are shared by every generator, and a type still used by a rack can't be removed.
8. **Settings**: the config (tags, run range, expansion flags, compatibility or standard mode, document fields).

The dashboard counts generators and builds, and lists them in recent activity.
`samples/generator-sample.xlsx` (invented data, written by `scripts/make-generator-sample.py`) is used by the engine tests and the Windows CI smoke test.

## Command line

```bash
python -m workbench_core.generators import  <workbook.xlsm> -o gen.json --report import-report.json
python -m workbench_core.generators check   gen.json
python -m workbench_core.generators build   gen.json -o build.json [--from N --upto N] [--prev old-build.json]
python -m workbench_core.generators diff    old-build.json build.json
python -m workbench_core.generators export  build.json --gen gen.json -o schedule.xlsx
python -m workbench_core.generators golden  <folder with workbooks and expected.json>
```

`--upto` is exclusive, as in the workbooks ("run below").

## Golden tests (real workbooks, kept local)

Project workbooks are **never committed**: this repository is public, and the workbooks hold project data.
Keep them in `samples/generators-local/` (git-ignored) or anywhere else, and point
`GENERATOR_FIXTURES` at that folder. Put an `expected.json` next to them:

```json
{"<generator id>": {"runs": 0, "rows": 0, "output_rows": 0, "cells": 0, "unresolved": 0, "no_template": 0, "duplicate_ids": []}}
```

Any subset of keys may be given. The golden runner:
- builds each workbook with its stored config and compares the counts;
- checks that a rebuild with unchanged inputs reports no changes;
- when a workbook holds a stored `Output`, compares it cell by cell by header, including type.

`core/tests/test_generators_io.py::test_golden_workbooks` is skipped when no workbooks are present.
All other tests use invented data.

## Import notes

- Template formulas map to computed columns:
  - `&` concatenation;
  - `EXACT(VLOOKUP(x, range, 1), x)` existence checks;
  - `VLOOKUP(..., 0)`, plain or `IF(x="","",...)` / `IF(x<>"",...,"")`-guarded;
  - `COUNTIF`.

  Any other formula is kept as text and listed as unmapped.
- Lookup sheets are imported whole, with columns named by letter, so `VLOOKUP(U2,Sheet!B:I,6,0)` becomes key column `B`, return column `G`.
- Runsheet formula columns use their cached values; the formula is kept on the column.
- An annotations row of input kinds (`Model / Number / Choice / Inbuilt`) becomes column `source` metadata.
- A column used as the key of a lookup whose table keys hold tag patterns is marked **raw**: written unexpanded, so the lookup matches the pattern.
- Reported data issues:
  - duplicate lookup keys;
  - template IDs in more than one block;
  - duplicate run numbers;
  - blank raw key columns;
  - runsheet values that look like tags.

## Behaviours kept in compatibility mode (PRD Appendix D)

- A blank value becomes `<<No Value Found>>`.
- `RunUpTo` is exclusive, and a non-numeric run counts as 0.
- Values are inserted unescaped, and later tags expand them.
- The parent lookup is case-sensitive.
- The existence check uses an approximate-match VLOOKUP.
- Space collapse runs three passes.
- `F=` is replaced anywhere in the text.
- Row directives pass through.
- The first template block wins.
- Literal template text keeps its stored type.
- The parent text ends in a trailing space.

`mode = "standard"` already applies these fixes:
- case-insensitive parents;
- an exact existence check;
- a full space collapse;
- leading `F=` only;
- `<<DELETE ROW>>` drops the row and `<<MANUAL ROW>>` is flagged;
- the parent text is trimmed;
- a non-numeric run is a Check error.

Still open:
- the `NO_PLC` behaviour;
- one-level nesting.
