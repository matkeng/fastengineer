---
title: List import: imports and files
group: Screens
order: 20
---
List import turns a file from someone else into a list of yours: a mechanical equipment list into the Load List, or a list of tags into an instrument list. You build a **recipe** of rules for reading the file. The file itself is never changed, and the same rules are applied to every later revision.

For a walk-through see [Import a MEL and make the Load List](help:howto-import-mel).

## The list of imports

![The list of imports](img/import-list.png)

To make an import, type a name, choose the kind of list and press **Create**.

| Kind | Maps its columns onto |
|---|---|
| MEL → load list | The fields of the Load List. Meant for a mechanical equipment list; gets the Strike through column |
| ELL → load list | The fields of the Load List |
| EEL → load list | The fields of the Load List. Meant for an electrical equipment list |
| LIL → load list | The fields of the Load List |
| PIL → instrument list | The fields of an instrument list. Meant for a tags list from Symbol detection |
| PSL → PID Symbols | The fields of the [PID Symbols](help:pid-symbols) list |

The [Project Master Load List](help:load-list) is made from the rows of every **MEL** and **EEL** import.

**New from settings…** makes an import from a settings file a colleague exported. See [Share settings and lists](help:howto-share).

**Delete** on a row removes the import, its files and its rules. Its loads stay in the Load List, marked deleted.

## An open import

![An import's Overview tab](img/import-overview.png)

Along the top:

| Button | What it does |
|---|---|
| **← All imports** | Back to the list |
| The name box | Rename the import |
| **Edits report .xlsx** | A workbook of what the import changes in its file, for the file's owner. See [Take in a revised MEL](help:howto-revised-mel) |
| **Check edits…** | Shows which of your edits the latest file has taken in |
| **Export settings**, **Import settings…** | Save the rules as a file, or replace them from one |
| **History** | The changes made to this import |
| **Discard**, **Save** | Edits are a draft, previewed live, until you press Save |

The tabs are the steps of the recipe, in the order they are applied. A number on a tab counts its rules.

| # | Tab | Rule |
|---|---|---|
| 1 | Columns | Hide or rename columns |
| 2 | Rows | Hide rows |
| 3 | Text columns | Add a column with the same value in every row |
| 4 | Overrides | Replace the value of single cells |
| 5 | Custom rows | Add rows that are not in the file |
| 6 | Find Replace | A new column from another, with whole values replaced |
| 7 | Calculated | A new column worked out by If / Else rules |
| 8 | Mapping | Which column fills which field of the list |

Steps 1 to 6 are on [the rules page](help:import-rules); see also [Calculated columns](help:import-calculated), [Mapping](help:import-mapping) and [Result](help:import-result).

## Files

Every upload is kept as a **revision**. The newest is the one used.

To upload, choose where the file comes from:

- **CSV file**: comma, semicolon, tab or `|` separated. A file that is not UTF-8 is read as Windows-1252, with a warning.
- **From Excel…**: a sheet or table chosen with the [Excel table wizard](help:excel-wizard).
- **From symbol detection**: the result of an analysis.

Then choose the **key column**, the one whose value identifies each row (usually the tag), and press **Upload**. The key column can differ from one revision to the next.

Headings and keys are made unique: a blank becomes `Blank`, and repeats get `_1`, `_2`.

**Delete** on a revision removes that file.

### When a revised file arrives

Upload it as the next revision. The same rules apply. Under the recipe, the Overview says either *Every rule applies to the latest file* or lists the **rules not applied**, such as a hidden row whose tag is not in the new file. Those rules are kept, in case the row comes back.

## Strike-through rows

A row struck through in a MEL usually means the equipment was deleted. A **MEL** import always gets one more column, **Strike through**, after the file's own:

| Value | When |
|---|---|
| Full Row | Every filled cell of the row is wholly struck through |
| Multiple Cells | Two or more cells are struck through |
| One Cell | One cell is wholly struck through |
| Partial Cell/s | Only part of the text of one or more cells is struck through |
| (blank) | Nothing is struck through |

Only an Excel file carries this formatting. A CSV upload gets the column blank, with a warning.

The column is like any other. Filter on it in **Rows** to untick struck-through rows, or use it in a calculated column, for example `<<Strike through>> == 'Full Row'`, mapped to the Load List's **Deleted** field so that struck-through rows are marked deleted in the Load List.
