---
title: The Excel table wizard
group: Screens
order: 3
---
Wherever the app reads a table from Excel (in [Compare tables](help:compare), and **From Excel…** in [List import](help:import-overview)), the same steps choose it.

## 1. Workbook

Drop an `.xlsx` or `.xlsm` file on the box, or click it to browse. The file is read on your own computer.

![The workbook step](img/wizard-workbook.png)

## 2. Sheet or table

Pick a whole worksheet, or a defined Excel table (its range and headings are already known).

![The sheet or table step](img/wizard-sheet.png)

## 3. Header row

Pick the row that holds the column names, from the list or by clicking it in the preview. A suggestion is already selected.

If the names are stacked over several rows (for example "Cable" above "Size" and "Cores"), set how many rows the header spans, up to four. They are joined: "Cable Size", "Cable Cores".

![The header row step](img/wizard-header.png)

## 4. Key column

Pick the column whose value identifies each row, such as the tag or cable number. For each column the step shows how many cells are filled, how many values are unique and how many are duplicated, and it suggests a likely key.

**Skip rows where the key is blank** leaves out notes, subtotals and spacer rows.

![The key column step](img/wizard-key.png)

Press **Use this table**.

## How cells are read

- **Values, not formulas.** The app reads the results Excel calculated and saved. If a formula has no saved result (for example the file was written by a program and never opened in Excel), the cell is blank and a warning says how many. Open the file in Excel and save it to fix that.
- **Merged cells** are split out: every cell of a merged range gets the top-left value. Copied values are shown in italics in the preview.
- **Strikethrough** is detected for each cell as none, partial (only some of the text is struck) or full. A row is *Struck out* when every filled cell is fully struck, and *Partly struck* when any cell is.
- Duplicate keys are flagged with ⚠, and every row keeps its Excel row number.

## Not supported

- `.xls` and `.xlsb` files. Save them as `.xlsx` first.
- Strikethrough applied by conditional formatting.
- Very large sheets may be slow: the whole sheet is read into memory.
