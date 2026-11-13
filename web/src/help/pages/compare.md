---
title: Compare tables
group: Screens
order: 2
---
Compare tables shows what changed between two revisions of a table: an old and a new sheet from Excel. It is opened from its card on the **Dashboard**; **← Dashboard** goes back.

For a walk-through see [Compare two revisions of a table](help:howto-compare).

## Choosing the two tables

Choose the **old** table, then the **new** table, each with the [Excel table wizard](help:excel-wizard): the workbook, the sheet or table, the header row and the key column. The two can come from two workbooks or from two sheets of one (**Use the same workbook as the old table**). Then press **Compare →**.

![Choosing the old table](img/compare-start.png)

## How rows and columns are matched

Rows are matched by **key value** and columns by **heading**, so the order of rows and columns does not matter.

| Status | Meaning |
|---|---|
| Added | The key is only in the new table |
| Deleted | The key is only in the old table |
| Struck out | Marked deleted in the new table (every filled cell, or the key cell, is struck through) but not in the old |
| Restored | Struck out in the old table, no longer in the new |
| Changed | One or more cells differ in value or in strikethrough |
| Unchanged | |

## Reading the result

![A comparison result](img/compare-result.png)

- Changed cells show `old → new`, the old value in red and the new in green.
- Added and removed columns are labelled in the heading.
- The grid opens on **Any change**. The chips above it (*added*, *deleted*, *struck out*, *restored*, *changed*, *unchanged*, *all rows*) filter by status.
- **Changed columns only** hides the columns with no differences.
- A warning chip appears when keys are duplicated. Duplicates are paired in the order they appear.

![Changed columns only](img/compare-changed-columns.png)

## Options

| Option | Effect |
|---|---|
| **Ignore case** | Keys, headings and text are compared ignoring capitals and extra spaces |
| **Strikethrough counts as a change** | A cell whose strikethrough changed is a changed cell. It is not counted on rows struck out or restored as a whole, where the status already says so |

Numbers are always compared as numbers, so `2.50` equals `2.5`.

## Exporting

- **Copy** and **CSV** export the rows and columns shown, with changed cells as `old → new`.
- **Excel (.xlsx)** saves a formatted workbook of the rows and columns shown, with three sheets:
  - **Differences**: one row per key, coloured by status, changed cells as `old → new`, the source strikethrough kept, with filters and a frozen heading.
  - **Cell changes**: one row per changed cell (key, column, kind of change, old, new, Excel rows).
  - **Summary**: the two tables, the counts, the options and any warnings.

## Starting again

**Change old table** and **Change new table** go back to the wizard for one side. **New comparison** clears both.
