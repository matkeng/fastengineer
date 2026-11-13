---
title: List import: result and export
group: Screens
order: 24
---
The **Result** tab shows what the recipe makes of the latest file.

![The Result tab](img/import-result.png)

## Two views

- **Combined table**: the file after every rule, with all its columns.
- **Load list** (or **Instrument list**, **PID symbols**): only the mapped fields, as they go into the list.

![The mapped load list](img/import-result-loadlist.png)

## Colours

| Colour | Meaning |
|---|---|
| Orange | An overridden cell |
| Green | A custom row |
| Red | A calculated cell that gave an error |

## Exporting

- **CSV** saves the combined table.
- **Excel (.xlsx)** saves it as a workbook with overridden cells, custom rows and errors highlighted, plus a Notes sheet.

The usual grid controls apply: filters, **Columns**, **Copy**.

## Where the rows go next

Nothing needs to be pushed. Once the import is **saved**:

- the rows of a MEL or EEL import are in the [Project Master Load List](help:load-list);
- every row of a MEL import, hidden or not, is in the [MEL](help:mel-list) project list;
- the rows of a PSL import are in [PID Symbols](help:pid-symbols).

Those lists always read the import's latest file through its saved rules.
