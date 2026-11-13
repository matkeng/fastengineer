---
title: Drawing List and Document List
group: Project lists
order: 17
---
Two registers: the project's drawings, and its documents (lists, schedules, datasheets and the like).

![The Drawing List](img/drawing-list.png)

Click a row, or **Add drawing** / **Add document**, to open the form. **Save** saves straight away.

## A drawing

![A drawing](img/drawing-form.png)

| Field | Rule |
|---|---|
| **Drawing number** | Required. Unique |
| **Project name** | Text. A new drawing starts with the open project's name |
| **Title 1**, **Title 2**, **Title 3** | Text |
| **Drawing discipline**, **Drawing type**, **Status** | Blank, or one of that list's items in the [Enums](help:enums) |
| **Revision** | Text |
| **Issue date** | A date, or blank |
| **Vendor drg number**, **Vendor reference** | Text |
| **Equipment reference** | One or more tags, separated by commas |
| **Scope** | Text |
| **Hyperlink** | Where the drawing is kept: a web address (`https://…`), or the path of a file or folder (`\\server\share\…`, `C:\…`) |

### The hyperlink

In the grid the hyperlink is a link that opens in a new window. The form has **Open** and **Copy** beside it. A web address opens in the browser. Whether a file path opens depends on the computer's settings, which is what **Copy** is for: paste the path into File Explorer.

### Equipment reference

A tag in the equipment reference that is in neither the MEL nor the Electrical Equipment List is flagged with ⚠ on the row. It never stops a save.

## A document

![The Document List](img/document-list.png)

The Document List is the same with **one Title** in place of three, and a **Document type** in place of the drawing type: Document number (required, unique), Project name, Title, Document discipline, Document type, Revision, Status, Issue date, Vendor doc number, Vendor reference, Equipment reference, Scope and Hyperlink.

## Excel export and import

One sheet with these headings. On import:

- a drawing or document keeps its identity by its number;
- a discipline, type or status is read by its code or its name. One that is not in the Enums refuses the file, naming the drawing;
- dates are read as `dd/mm/yyyy`, `yyyy-mm-dd` or an Excel date.
