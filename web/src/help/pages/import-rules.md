---
title: List import: the rules
group: Screens
order: 21
---
The first six tabs of an import each hold one kind of rule. Rules run in the order of the tabs every time the data is read, and the uploaded file is never changed. Edits are a draft, shown live, until you press **Save**.

## Columns

Hide the columns you do not need, and rename the ones you keep. Later steps use the new names.

![The Columns tab](img/import-columns.png)

- Untick **Keep** to hide a column. **Show all** and **Hide all** set every column.
- Type a **New name** to rename a column. It keeps its position.
- The key column is always kept and cannot be renamed.
- **Rules for columns not in the latest file** lists rules for columns a revised file no longer has, each with **remove rule**.

## Rows

Untick the rows that are not wanted in the list: notes, spares, tanks and other equipment that is not a load.

![The Rows tab](img/import-rows.png)

- Rows are remembered by key, so the choice carries over to revised files.
- Type a **Reason** beside a hidden row. It goes in the edits report.
- Filter the grid, then use **Un-check all filtered rows** or **Check all filtered rows** to set many at once.
- In a MEL import, a row unticked here still appears in the [MEL](help:mel-list) project list, marked *not a load*.

## Text columns

Add a column that has the same value in every row, for example `Source` = `MEL`. Press **Add text column**, then type the column name and the value.

![The Text columns tab](img/import-text.png)

A single cell of a text column can still be changed with an override.

## Overrides

Change the value of one cell without editing the file.

1. Click the cell.
2. Type the **New value** and a **Reason**.
3. Press **Apply**.

![Overriding a cell](img/import-override-dialog.png)

![An overridden cell](img/import-overrides.png)

Overridden cells are shown in orange. Hover over one to see the file's value. To remove an override, click the cell and press **Clear override**; **Clear all** removes every override.

## Custom rows

Add rows that are not in the file, such as a load the mechanical list missed. Press **Add row**, type the key (the tag), a reason and the values, and press **Add**.

![Adding a row](img/import-custom-dialog.png)

![A custom row](img/import-custom.png)

Empty cells show as "-". Editing a custom row replaces it; **Delete** removes it.

## Find Replace

Make a new column from an existing one, with whole values replaced. Use it to turn the file's wording into yours, for example the file's `DOL` into `Direct on line`.

![The Find Replace tab](img/import-replace.png)

1. Press **Add find/replace column**.
2. Choose the **Column to read** and type the **New column name**.
3. The page lists the column's values, each once and sorted, with how many rows have it. Beside each, type what replaces that **whole value**. Leave the box empty to keep the value. Tick **Blank** to make it empty.

Good to know:

- Up to 100 values are listed at a time. The filter box finds the others.
- The column that is read is not changed. The new column gets the replaced values.
- Rows added in Custom rows are included.
- Several find/replace columns can be added, and each can read the ones before it. ↑ ↓ reorder them.
- A replacement for a value that a later file no longer has is kept and listed, in case the value comes back.

## Reasons and the edits report

Overrides, hidden rows and custom rows each take a reason. **Edits report .xlsx** lists them all for the owner of the file, so that the next revision can include them. See [Take in a revised MEL](help:howto-revised-mel).
