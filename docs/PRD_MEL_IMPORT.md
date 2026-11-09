# PRD: CSV Import and MEL (Mechanical Equipment List) Transformation Flow

**App:** `csvimport` (Django, mounted at `/csvimport/` in `myproject/urls_tenants.py`)
**Status:** Documents the implementation as it exists on 2026-11-09. This is a
reverse-engineered PRD: it describes what the code does today, then lists the gaps.
**Primary target list:** `MEL` (Mechanical Equipment List). The same code path serves
`ELL`, `EEL`, `PIL` and `LIL`, but several redirects and links hardcode `MEL`
(see section 11).

---

## 1. Purpose

Engineers receive a Mechanical Equipment List from a mechanical team as a CSV. The
electrical team needs that list reshaped into an Electrical Load List (`loaddesign.ElecLoad`
rows). Every project's MEL has different column names, junk columns, rows that are not
loads, typos, and missing columns.

`csvimport` lets the user:

1. Upload the MEL CSV and pick the column that uniquely identifies a row (the key column,
   usually the equipment tag).
2. Build a **persistent, re-applicable transformation recipe** on top of the raw file:
   hide and rename columns, hide rows, add constant text columns, override individual
   cells, append hand-written rows, and add calculated columns.
3. Map the transformed columns onto the fields of `ElecLoad`.
4. Preview and export the result, and push it into the load list.

The key design property is that the **raw CSV is never modified**. Every user decision
is stored as a small rule row keyed by the column header or row key value, and the rules
are re-applied in a fixed order each time the data is read. When a revised MEL is
uploaded, the same recipe is applied to the new file.

---

## 2. Scope

### In scope (live code)

| Area | Code |
|---|---|
| Upload wizard | `views.MyWizard`, `forms.UploadCSVForm`, `forms.SelectKeyColumnForm` |
| File management | `views.CsvFile_ListView`, `csvfile_edit_view`, `CsvFile_DeleteView` |
| Recipe hub | `views.Csv2Combined_Detail` |
| Column filter / rename | `views.Csv2CombinedColumnFilter` |
| Row filter | `views.Csv2CombinedRowFilter` |
| Text columns | `views.Csv2CombinedTextColums` |
| Cell overrides | `views.Csv2CombinedOverrides` |
| Custom rows | `views.Csv2CombinedCustomRows` |
| Auto (calculated) columns | `views.Csv2CombinedAutoColums`, `ApplyAutoColumns` |
| Transpose columns | `views.Csv2CombinedTranspose`, `Csv2CombinedLTransposeItems` (UI only, not applied) |
| Field mapping | `views.Csv2CombinedLoadListMap` |
| Result | `views.Csv2CombinedFullView`, `Csv2CombinedExportCsv`, `BuildFinalCombinedData` |
| Hand-off | `loaddesign.views.updateLoadListFromMEL` |

### Out of scope (obsolete, still in the module)

`CsvIndex`, `CsvFileSet`, `CsvValue`, `CsvProfile`, `CsvCalcColumn`, `CsvCalcSet`,
`LoadListMap`, the `csv_upload` / `csv_detail` / `csv_compare` views, and all the
commented-out DRF API routes in `urls.py`. The sibling folders `csvimport2/` and
`csvimport3/` are not in `INSTALLED_APPS` and have no models. The `new-stuff/` folder
contains unused generated JS modules.

---

## 3. Users and entry points

Single user role: a logged-in engineer with a default project. There is no
per-recipe permission model.

Sidebar (`bs5/templates/bs5/partials/sidebar.html`) exposes two links, both hardcoded
to `MEL`:

- **CSV Files** -> `/csvimport/combined/MEL/files/` (file list, upload, revisions)
- **MEL Combined** -> `/csvimport/combined/MEL/` (the recipe hub)

The load-list side triggers the import at `/loaddesign/ElecLoads/update/MEL/`.

### Authentication and tenancy

- Function views use `@project_login_required` (`myproject/decorators.py`). It requires
  an authenticated user with `user.default_project` set and injects
  `current_project` (a project id) as a view kwarg.
- Class views use `ProjectLoginRequiredMixin` (`myproject/mixins/matt_mixins.py`), which
  reads `request.session['current_project']` instead.
- The two mechanisms read the project from different places. They agree only while
  the session value and the user's default project are the same.
- The app runs under `django-tenants`; each tenant schema has its own tables. Every
  recipe object inherits `projects.models.CommonProject` (UUID pk, `project` FK,
  `added_by`, history) or carries a FK to one that does.

---

## 4. Data model

All recipe tables hang off one `Csv2Combined` row per target list.

```
Csv2Combined (target_list='MEL', project)
 ├── files            CsvFile          raw upload, one row per revision
 ├── filter           CsvFilter        COL: hide/rename a column; ROW: hide a row
 ├── textcols         TextColumn       constant-value column
 ├── override         CsvOverride      one cell value, keyed (row key, column name)
 ├── custom_row       CustomRow        an appended row
 │     └── items      CustomItem       (col_name, value) pairs for that row
 ├── autos            AutoColumn       calculated column (statement / true / false / error)
 ├── transpose_columns TransposeColumn (+ TransposeItem) tagging UI, not applied to data
 └── mapfields        MapField         ElecLoad field -> source column or manual value
```

### 4.1 `Csv2Combined`

| Field | Notes |
|---|---|
| `target_list` | `MEL` / `ELL` / `EEL` / `PIL` / `LIL`. **`unique=True` globally**, not per project (see 11). |
| inherits `CommonProject` | `project`, `added_by`, history. |

### 4.2 `CsvFile` (the raw upload)

| Field | Notes |
|---|---|
| `file_name` | Original upload name. |
| `num_rows`, `num_cols` | Counted at upload. `num_rows` includes the header line. |
| `headers` | JSON list of **de-duplicated, stripped** header names used as dict keys. |
| `headers_original` | JSON list of the header names exactly as in the file. |
| `key_header` | The chosen key column name (from `headers`). |
| `csv_data` | JSON **string** (double-encoded inside a `JSONField`) of a list of row dicts, keyed by `headers`, with key values made unique and rows sorted by key. |
| `csv_data_original` | Same shape, before key de-duplication and sorting. |
| `rev` | Auto-incremented per combined in `save()`: `max(rev)+1`. `is_latest` compares against the max. |

Only the **latest revision** is ever read by the transformation pipeline
(`LoadCsvFile` orders by `-rev` and takes the first).

### 4.3 Recipe rows

| Model | Key | Payload |
|---|---|---|
| `CsvFilter` (`filter_type='COL'`) | `index_name` = header | `is_visible`; `index_override` = new header name, or the sentinel `"No-Override-Applied"` |
| `CsvFilter` (`filter_type='ROW'`) | `index_name` = row's key value | `is_visible` (only `False` rows are ever created) |
| `TextColumn` | `col_unique` = new column name | `default_value`; `col_name` is the user-typed name before uniquing |
| `CsvOverride` | (`row_index` = key value, `col_index` = header) | `over_value` |
| `CustomRow` + `CustomItem` | `row_name` = key value | one item per column |
| `AutoColumn` | `col_unique` | `statement`, `true_val`, `false_val`, `error_val`, `order_num` |
| `MapField` | (`combined`, `field_name`) | `column_name` (a header, or `* Manual Entry *`) and `manual_value` |

Every rule is keyed by a **name** (header string or key-column value), never by a
position. That is what lets a recipe survive a re-upload: as long as the new file
has the same header names and the same tags, the rules still land.

---

## 5. End-to-end user flow

```
Upload wizard ──► CsvFile rev N ──► Combined detail hub
                                        │
          ┌──────────┬──────────┬───────┼────────┬───────────┬───────────┐
       Columns     Rows      Text   Overrides  Custom Rows  Auto Cols   Mapping
          └──────────┴──────────┴───────┼────────┴───────────┴───────────┘
                                        ▼
                      BuildFinalCombinedData()  (section 6)
                                        │
                         ┌──────────────┼──────────────────┐
                     Full View      Export CSV     loaddesign.updateLoadListFromMEL
```

Every editor page follows one pattern: the view runs part of the pipeline to build
the table the user sees, embeds it as JSON in the page, an AngularJS controller
edits it client-side, and **Save** POSTs the whole edited JSON back to the **same
URL**. The view diffs it against the database, writes the rule rows, and returns
`{"redirect_url": ...}` which the browser follows back to the hub.

### 5.1 Upload (`/csvimport/csvfile/upload/`)

`MyWizard` is a `formtools.SessionWizardView` with two steps, both rendered by
`CsvFile/upload_form.html`. Uploaded files are parked in
`MEDIA_ROOT/temp_wizard_files/` between steps.

**Step 1, `UploadCSVForm`:** target list (`csv_target`, default `MEL`) and the file.

**Step 2, `SelectKeyColumnForm`:** the view calls `get_csv_file_headers()` on the
step-1 file to populate a choice list of headers, and shows file name, row count and
column count read from the session.

**`done()`** does the parsing and persistence:

1. `get_csv_file_headers()` decodes as UTF-8 (a non-UTF-8 file aborts), reads the
   first row and makes headers unique: strip whitespace, blank -> `Blank`, repeated
   name `X` -> `X_1`, `X_2`...
2. `get_csv_file_json()` re-reads the file with `csv.DictReader` using those unique
   headers, producing a list of dicts.
3. `check_key_column_unique()` strips key values, blank -> `Blank`, and suffixes
   duplicates `_1`, `_2`... **in place**. This is what guarantees the key column can
   be used as a row identifier by every later rule.
4. Rows are sorted by key value.
5. `Csv2Combined.get_or_create(target_list, project_id, added_by)`.
6. A `CsvFile` is saved with both the processed and the original data as JSON
   strings; `save()` assigns the next `rev`.
7. Redirect to the file list for that target.

There is no row limit; the whole file is held in memory and stored in one JSON column.

### 5.2 File list, edit, delete (`/csvimport/combined/MEL/files/`)

- `CsvFile_ListView` pages 4 per page, newest revision first, and badges the latest
  one. The latest is the only one the pipeline uses.
- `csvfile_edit_view` edits `file_name`, `combined`, `rev` and shows the first ten
  original rows. The form declares a `key_header_value` choice but it is not in
  `Meta.fields`, so **the key column cannot be changed after upload**.
- `CsvFile_DeleteView` deletes a revision. Deleting the latest promotes the previous
  one by virtue of `-rev` ordering.

### 5.3 Recipe hub (`/csvimport/combined/MEL/`)

`Csv2Combined_Detail` renders `Csv2Combined/detail.html`: the key header, the raw
row and column counts, and one row per rule type with its count and a button into
that editor, plus Mapping and Full View.

### 5.4 Columns (`/combined/MEL/columns/`)

The one editor that is plain HTML + `fetch`, not Angular (`select_columns.html`).

- **GET:** one table row per header in `CsvFile.headers`: original name, editable new
  name, Active checkbox, and hidden `key{i}` (existing `CsvFilter` id or `-1`) and
  `original{i}`. The key column's text box is still rendered but the server ignores
  edits to it.
- **POST:** JSON of the form fields. For each index `i`: new name != original ->
  `index_override` = new name, else the sentinel; unchecked -> `is_visible=False`.
  The key column is forced visible and un-renamed. Rows are updated by id or created.
  Note a `CsvFilter` row is written for **every** header, even untouched ones.

### 5.5 Rows (`/combined/MEL/rows/`)

- **GET:** raw data with the column filter applied; each row gains `Active`,
  `RowHead` (its key value) and `CsvFilterId`. Existing `ROW` filters set `Active`.
- **UI** (`CsvCombinedSelectRows_ctl.js`): paged table (7 rows), per-column filter
  row (`*` contains, `!*`, `=`, `!=`, `B` blank, `S` starts, `E` ends), single-column
  sort, Select All / Select None operating on the **filtered** set, live selected count.
- **POST:** for a row with `CsvFilterId == -1` and `Active == false`, create a hidden
  `ROW` filter; for an existing filter, write `is_visible`. Rows that were never
  hidden get no DB row.

### 5.6 Text columns (`/combined/MEL/text/`)

Adds a column whose every cell is the same constant (for example `load_type = Motor`
or `source = MEL`).

- **GET:** three sample rows, the column names, and existing `TextColumn`s with
  `status: "Original"`.
- **UI:** modal with Column Name and Default Value. The client-side name is made
  unique against existing headers and other new columns (`Name_Copy(1)`...).
- **POST:** rows carry `status` of `Added` / `Modified` / `Deleted` / `Original`.
  Create, update by `CsvFilterId`, or delete. A column whose unique name equals an
  existing row key is skipped (a leftover from copy-pasting the custom-rows handler).

### 5.7 Overrides (`/combined/MEL/overrides/`)

Changes one cell, identified by (key value, column name), without touching the file.

- **GET:** pipeline up to and including text columns. Every cell is expanded to
  `{value, CsvFilterId, override, sort}` where `override` is the stored value or the
  sentinel `"##%None%##"`.
- **UI** (`CsvCombinedOverrides_ctl.js`): every cell is a button; clicking opens a
  modal pre-filled with the current value. Overridden cells render in red. "Clear
  Override" restores the sentinel. Column filters and sort read `.value` / `.sort`.
- **POST:** for each cell where `override != value` and not the sentinel: create or
  update `CsvOverride`; otherwise delete any existing override for that cell. So
  typing the original value back **removes** the override rather than storing a no-op.
- Overrides can target text-column cells because text columns are applied before
  overrides in the pipeline (section 6). They cannot target custom rows or auto
  columns, which are applied after.

### 5.8 Custom rows (`/combined/MEL/custom/`)

Appends rows that are not in the MEL at all (for example a load the mechanical list
forgot, or a load centre).

- **GET:** headers from the pipeline up to text columns; existing `CustomRow`s are
  expanded into dicts with every header defaulting to `"XXXX"` and overlaid with
  their `CustomItem`s, plus `rowIndex`, `RowHead`, `Status: "Original"`, `CsvFilterId`.
- **UI** (`CsvCombinedCustomRows_ctl.js`): Add Row opens a modal with one text input
  per header, defaults `-`. Client-side validation refuses a key value of `-` or one
  that duplicates another **custom** row's `RowHead`. Edit marks `Status: "Edited"`,
  Delete marks `"Deleted"` (or removes an unsaved `New` row). Deleted rows are
  hidden from the table but still sent.
- **POST:** skips any row whose `RowHead` matches a real data row key. `New` creates
  the `CustomRow` and one `CustomItem` per non-meta key. `Edited` **creates new
  `CustomItem`s without deleting the old ones** (see 11). `Deleted` cascades.
- When applied (section 6), a custom row's cells default to `-` for any header it
  has no item for, and items whose `col_name` is no longer a current header are
  ignored.

### 5.9 Auto columns (`/combined/MEL/auto/`)

Calculated columns evaluated per row with
[`asteval`](https://pypi.org/project/asteval/) 0.9.25.

- **Model:** `statement` (a boolean expression), `true_val`, `false_val`, `error_val`,
  `order_num`.
- **UI** (`CsvCombinedAutoColumns_ctl.js`): modal with four text fields and, beside
  each, a column picker plus **Add** that appends `<<Column Name>>` to the field.
  The picker lists current headers plus other auto columns (so one auto column can
  use another's result). Up/down buttons swap `order_num` with the neighbour.
  Save POSTs the list with `Added` / `Modified` / `Deleted` statuses.
- **Evaluation** (`ApplyAutoColumns`), per column in `order_num`, per row:
  1. Replace every `<<key>>` in `statement`, `true_val`, `false_val` with
     `str(row[key])` by plain string substitution. Values are inserted **unquoted**;
     a text value must be wrapped in quotes in the expression by the user
     (`"<<Equipment Type>>" == "Pump"`).
  2. `Interpreter()(statement)`. If it evaluates to `True`, evaluate `true_val`; if
     `False`, evaluate `false_val`. Any evaluation error yields `error_val`.
  3. A result of `None` becomes `error_val`.
  4. Write `row[col_unique] = result`.
- Because columns run in order and later ones see earlier results, the feature
  supports chained derivations (`kW` from `HP`, then `Amps` from `kW`).

### 5.10 Transpose columns (`/combined/MEL/transpose/`)

A tagging UI: a `TransposeColumn` names a set of source columns (`target_col_list`)
and a `tag_list`; the items page lists every distinct concatenation of those
columns' values (`"A - B"`) and lets the user assign one tag to each
(`TransposeItem`). **Nothing in `BuildFinalCombinedData` applies it**, so it has
no effect on the output today. The hub page does not link to it.

### 5.11 Mapping (`/combined/MEL/map/`)

Maps the **final** column set onto `ElecLoad`.

- **GET:** `get_or_create` a `MapField` for each name in the hardcoded
  `ElecLoad_Fields` list (24 fields: `area`, `sub_area`, `tag`, `equip_qty`,
  `standby_qty`, `multi_load`, `desc`, `equip_type`, `equip_subtype`, `load_units`,
  `load_rating`, `load_voltage`, `csv_row_num`, `phases`, `status`, `starter_type`,
  `load_type`, `starter_addons`, `load_addons`, `field_addons`, `is_a_loadcentre`,
  `loadcentre`, `supplied_from`, `is_deleted`). Column choices are the output
  headers plus `* Manual Entry *`.
- **UI** (`map_fields.html`): one select per field; a text box appears when
  `* Manual Entry *` is chosen.
- **POST:** writes `column_name` and `manual_value` by `MapField.id`.

`LoadListMap` (a one-to-one with a column per `ElecLoad` field) is an earlier design
of the same thing and is not used by the live view.

### 5.12 Full view and export

- `/combined/MEL/view/` renders the full pipeline output in an Angular table with the
  same filter/sort bar and a Select Columns modal (client-side hide only). Export CSV
  button links to:
- `/combined/MEL/csv/` which streams `MEL_export_<timestamp>.csv` with the final
  headers and rows.

### 5.13 Hand-off to the load list (`loaddesign`)

`loaddesign.views.updateLoadListFromMEL` (`/loaddesign/ElecLoads/update/MEL/`):

1. Soft-deletes every `ElecLoad` with `source="MEL"` in the project.
2. Calls `csvimport.views.BuildFinalCombinedData` for the `MEL` combined.
3. Splits `MapField`s into column mappings and manual constants.
4. For each output row builds a dict of `ElecLoad` field -> value and calls
   `addLoad()`, which finds an existing MEL load by `tag`, else by `desc`, else
   creates one; un-deletes it; coerces numeric fields with `is_number()` (non-numeric
   -> `-9999`); parses `is_a_loadcentre` as the string `"true"`; sets
   `status="INIT"`, `source="MEL"`.

So the import is **idempotent by tag**: re-running after a revised upload updates
matching loads and soft-deletes loads that disappeared from the list.

---

## 6. The transformation pipeline

`BuildFinalCombinedData(request, combined, project)` is the single source of truth
and is called by Full View, Export, and `loaddesign`. Order is load-bearing:

| # | Step | Function | Effect | Why this position |
|---|---|---|---|---|
| 0 | Load | `LoadCsvFile` | Latest `CsvFile.csv_data` -> list of dicts; `key_header` | |
| 1 | Column filter | `ApplyColumnFilter` | Delete hidden columns; `dict.pop` + re-insert renamed ones (renamed columns move to the end of the dict). | Every later rule is keyed by the **new** header names. |
| 2 | Row filter | `ApplyRowFilter` | Remove rows whose key value has a hidden `ROW` filter. | Before overrides so no work is done on hidden rows. |
| 3 | Text columns | `ApplyTextColumns` | `row[col_unique] = default_value` for every row. | Before overrides so a text column cell can be individually overridden. |
| 4 | Overrides | `ApplyOverrides` | `row[col] = value` where key matches. | After text columns, before custom rows. |
| 5 | Custom rows | `ApplyCustomeRows` | Append rows; default `-` per header; apply items whose `col_name` is a current header. | After overrides, so custom rows cannot be overridden; before auto columns so they get calculated values too. |
| 6 | Auto columns | `ApplyAutoColumns` | Evaluate in `order_num`. | Last, so expressions can read every other column, including text columns and custom rows. |

The editor views each run a **prefix** of this pipeline to build what the user sees:
Columns reads the raw headers; Rows and Transpose run step 1; Text and Auto run
step 1; Overrides and Custom Rows run steps 1 to 3; Mapping, Full View and Export
run all six.

Each step is O(rules x rows) with Python loops over lists of dicts. Data volumes are
hundreds to low thousands of rows, so this is fine in a request.

---

## 7. Frontend architecture

- Base template `bs5/Base_BS5.html` (Bootstrap 5). Each editor page loads
  **AngularJS 1.8.2 from Google's CDN** and one controller from
  `static/csvimport/controllers/`. Some pages also load jQuery and FontAwesome from
  CDNs.
- The view serialises its context with `json.dumps(...)` and in some views runs
  `.replace("False","false").replace("True","true")` on the result (a hack that would
  corrupt any cell whose text contains `True`/`False`). It lands in the page as
  `var getInitialData = function(){ return {{ pushList|safe }} }` inside `{% verbatim %}`.
- Controllers keep three arrays: `allTableData` (everything, what gets POSTed),
  `filteredList`, and `tableData` (the current 7-row page). Filtering and sorting are
  client-side and are **view state only**; they are never saved.
- Save POSTs `allTableData` as JSON to `$location.absUrl()` with the `csrftoken`
  cookie in `X-CSRFToken`. Buttons flip red -> green while in flight.
- Row-level change tracking uses a `status` / `Status` string per item: `Original`,
  `Added`/`New`, `Modified`/`Edited`, `Deleted`. The naming differs between editors.
- `Csv2Combined/transpose_columns.html` injects a Django URL with a `__target__`
  placeholder for the controller to substitute; the other pages rely on the current URL.

---

## 8. URL map (live routes)

| URL (under `/csvimport/`) | Name | View |
|---|---|---|
| `csvfile/upload/` | `CsvFile_Upload` | `MyWizard` |
| `csvfile/<pk>/edit/` | `CsvFile_EditView` | `csvfile_edit_view` |
| `csvfile/<pk>/delete/<target>/` | `CsvFile_DeleteView` | `CsvFile_DeleteView` |
| `combined/<target>/files/` | `CsvFile_List` | redirect to page 1 |
| `combined/<target>/files/<page>/` | `CsvFile_List_Page` | `CsvFile_ListView` |
| `combined/<target>/` | `Csv2Combined_Detail` | hub |
| `combined/<target>/columns/` | `Csv2CombinedColumnFilter` | |
| `combined/<target>/rows/` | `Csv2CombinedRowFilter` | |
| `combined/<target>/text/` | `Csv2CombinedTextColums` | |
| `combined/<target>/overrides/` | `Csv2CombinedOverrides` | |
| `combined/<target>/custom/` | `Csv2CombinedCustomRows` | |
| `combined/<target>/auto/` | `Csv2CombinedAutoColums` | |
| `combined/<target>/transpose/` | `Csv2CombinedTranspose` | |
| `combined/<target>/transpose/<id>/` | `Csv2CombinedTransposeItems` | |
| `combined/<target>/map/` | `Csv2CombinedLoadListMap` | |
| `combined/<target>/view/` | `Csv2CombinedFullView` | |
| `combined/<target>/csv/` | `Csv2CombinedExportCsv` | |
| `` (root), `view/<pk>/`, `compare/..`, `data/csvheads/..` | legacy `CsvIndex` views | obsolete |

---

## 9. Dependencies

Django 4.2, django-tenants 3.4.7, django-formtools 2.5.1 (`SessionWizardView`),
django-crispy-forms 2.0, django-postgres-copy 2.7.4 (`copyMgr` on every model, used
only by the `csvimport_In` / `csvimport_Out` management commands that bulk
export/import every table to `./csv/Out|In/csvimport/*.csv` for one hardcoded tenant),
asteval 0.9.25, AngularJS 1.8.2 (CDN), Bootstrap 5.

---

## 10. Functional requirements as implemented

| ID | Requirement | Where |
|---|---|---|
| FR-1 | Upload a UTF-8 CSV against a named target list; reject non-UTF-8. | `get_csv_file_headers` |
| FR-2 | Choose a key column from the file's headers before saving. | wizard step 2 |
| FR-3 | Make headers and key values unique deterministically so rules can key on them. | `get_csv_file_headers`, `check_key_column_unique` |
| FR-4 | Keep every uploaded revision; the newest is the active one. | `CsvFile.rev`, `LoadCsvFile` |
| FR-5 | Hide or rename any column except the key column. | Columns |
| FR-6 | Hide any row by its key value. | Rows |
| FR-7 | Add constant-value columns. | Text |
| FR-8 | Override any individual cell, including in text columns; clearing restores the source value. | Overrides |
| FR-9 | Append hand-entered rows with a unique key. | Custom Rows |
| FR-10 | Add ordered, chainable calculated columns with an if/else expression and an error fallback. | Auto Columns |
| FR-11 | Map output columns (or constants) to each `ElecLoad` field. | Mapping |
| FR-12 | Preview the final table with filter and sort; export it as CSV. | Full View, Export |
| FR-13 | Push the result into the load list idempotently by tag, soft-deleting loads no longer present. | `loaddesign.updateLoadListFromMEL` |
| FR-14 | Rules survive a re-upload as long as header names and key values are unchanged. | name-keyed rule tables |

---

## 11. Known issues, gaps and technical debt

Found while reading the code; none has been fixed in this document's commit.

**Correctness**

1. **`Csv2Combined.target_list` is `unique=True` globally.** Within one tenant only
   one project can ever have a `MEL` combined; a second project's upload raises an
   `IntegrityError` at `get_or_create`. The lookup also includes `added_by`, so a
   second user on the same project hits the same error.
2. **Editing a custom row duplicates its items.** The `Edited` branch creates new
   `CustomItem`s without deleting the old ones. `ApplyCustomeRows` then applies items
   in an undefined order, so the displayed value after an edit is not guaranteed to
   be the latest.
3. **Every redirect and the Columns page's fetch URL hardcode `'MEL'`.** Saving any
   editor for `ELL`/`EEL`/`PIL`/`LIL` lands the user on the MEL hub, and the Columns
   page would write its filters to the MEL combined.
4. **`LoadCsvFile` indexes `[0]` on an empty queryset.** A combined with no file
   (for example after deleting all revisions) 500s on every page.
5. **Boolean-to-JSON text replace** (`.replace("True","true")`) runs over the
   serialised data and rewrites any cell containing those words.
6. **Key column cannot be changed after upload** (form field not in `Meta.fields`),
   and **row filters / overrides / custom rows are orphaned** if a later revision
   changes a key value or a header name. Nothing reports orphaned rules.
7. **`Status` validation for custom rows only checks other custom rows** client-side;
   the server silently drops a custom row whose key matches a real row.
8. **Transpose columns are configured but never applied** to the output.
9. **`num_rows` counts the header line**, so the file list over-reports by one.
10. **Five live code paths call `printjson` with one argument and will raise
    `TypeError`.** `views.py` gets `printjson` only from
    `myproject.commonfunctions`, whose signature is `printjson(data, text_string)`.
    The one-argument version lives in `myproject/view_functions.py`, which nothing
    here imports. Affected, as the source stands on disk:
    - Auto Columns save (`views.py:386`)
    - Text Columns save (`views.py:613`)
    - Overrides save, on the first changed cell (`views.py:1219`)
    - Custom Rows save (`views.py:1279`)
    - Custom Rows **page load** (`views.py:1330`)

    If these pages work on the running server, the deployed code differs from the
    files on disk. This was established by reading the source; the app was not run.

**Robustness and security**

11. `asteval` is sandboxed but still evaluates user-authored expressions server-side
    per row; `<<col>>` substitution is textual, so a cell value containing quotes or
    operators changes the expression's meaning.
12. No `transaction.atomic()` around any multi-row save; a failure half-way leaves a
    partial recipe.
13. No file size cap on upload; the whole CSV is parsed in memory and stored twice as
    JSON strings inside `JSONField`s (double-encoded, so Postgres JSON operators cannot
    query it).
14. Angular, jQuery and FontAwesome load from public CDNs; the editor pages do not
    work offline.
15. Dozens of `print()` debug statements run in request handlers, including dumping
    full payloads with `printjson` (see item 10).
16. `tests.py` is empty. There is no automated coverage of the pipeline order, the
    uniquing rules or the hand-off.

**Maintainability**

17. Roughly 1,600 of `views.py`'s 2,727 lines are the obsolete `CsvIndex` generation
    and commented-out DRF API, plus `_old` copies of live views.
18. Two auth mechanisms read the current project from different places (section 3).
19. The hub page does not link to Transpose; the Auto Columns page is titled
    "Custom Rows"; the mapping page is `map_fields.html` while the dead
    `LoadListMap` model suggests a different design.

---

## 12. Suggested next steps (not implemented)

Ordered by value to the MEL flow:

1. Fix item 10 first by removing or correcting the one-argument `printjson` calls,
   since it blocks four of the six editors from saving.
2. Fix items 1 to 4 above: scope the uniqueness to (`project`, `target_list`),
   delete-then-recreate items on custom-row edit, use `target` in every redirect, and
   guard the empty-file case with a message.
3. Add a "rule health" panel to the hub that lists row filters, overrides and custom
   rows whose key value or header no longer exists in the latest revision.
4. Replace the text `True`/`False` replace with `json.dumps` of native booleans
   (Angular parses JSON booleans fine).
5. Wrap each editor's POST in `transaction.atomic()`.
6. Vendor the JS libraries into `static/`.
7. Add pytest coverage for `BuildFinalCombinedData` ordering and for
   `check_key_column_unique` / `get_csv_file_headers`.
8. Either apply Transpose in the pipeline (as a tag-lookup column) or remove it.
9. Move obsolete models and views out of the app once the `csvimport_In/Out` dumps
   no longer need them.
