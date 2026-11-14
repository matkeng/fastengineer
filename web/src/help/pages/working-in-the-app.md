---
title: Working in the app
group: Getting started
order: 3
---
Most screens work the same way. This page covers what they share.

## Finding your way

- The **menu bar** switches between sections. An orange dot ● on a section means it has unsaved changes.
- **Project lists** has a sidebar of lists in groups: Project lists, Loads and panels, Instruments, Drawings and documents, Enums, and Project master lists. The number beside a list is how many rows it has.
- The **Help** button in the title bar opens the help page for the screen you are on.
- The **status bar** at the bottom shows the engine's state, the open project and your user name.

![Project lists, with the sidebar of lists](img/plant-areas.png)

## Choosing a project

The **Project** box in the title bar lists the projects you can open. Each project has its own data: nothing is shared between projects. Switching project reloads the app in the other one. If you have unsaved changes you are asked first.

If the box is missing, there is only one project. If you see "No project", ask an administrator to add you to one.

## Backing up and restoring a project

On the **Projects** screen (administrators; on your own PC, you):

- **Back up…** on a project saves all of it as one .zip file: its data and change log, its drawings and page images, and the PDFs attached to load types. It is safe to do while people are working.
- **Restore from a backup** takes such a file and makes a **new** project from it, named after the original with the date, for example *Plant A (restored 2026-11-14)*. No existing project is changed, so the original and the restored copy can both be opened and compared. Archive the one you no longer need.

A backup made by a newer version of the app is refused until the app is updated.

## Saving

There are two kinds of screen:

- **Save and Discard buttons** (Plant Areas, Equipment Packages, Enums, PLC List, Distribution Panels, Instrument Runsheet, a list import, a deliverable). Your edits are a draft until you press **Save**. **Discard** goes back to what was saved.
- **Forms that save straight away** (Load Types, codes, Cable Types, Motor Data, drawings…). Click a row to open its form; **Save** in the form saves that row. Choices made directly in the Load List (plant area, load type, supplied from) are also saved as soon as they are made.

A save that breaks a rule is refused, and the message says which value is wrong: a duplicate tag, a missing required value, or something that is still in use elsewhere.

### Changed by someone else

On a shared server, if two people have the same record open and both save, the second save is refused with the name of whoever saved first. Nothing is overwritten. Open the record again to get their version, then make your change again. Editing different records at the same time is fine.

## Grids

Lists shown as a grid share these controls:

| Control | What it does |
|---|---|
| Column headings | Click to sort; click again to reverse |
| Filter boxes under the headings | Show only the rows that match; a drop-down filters on one value |
| **Search all** | Finds text in any column |
| **Columns** | Show or hide columns |
| **Copy**, **CSV** | Copy the rows shown, or save them as a CSV file |
| Entries per page, and the page buttons | Move through long lists |

Click a row to edit it in a form.

## Spreadsheet-style grids

Template rows, the Instrument Runsheet and PLC card types are edited in a grid that behaves like a spreadsheet:

- Type, or press <kbd>Enter</kbd>, to edit a cell.
- <kbd>Ctrl</kbd>+<kbd>C</kbd> and <kbd>Ctrl</kbd>+<kbd>V</kbd> copy and paste, including blocks of cells from Excel.
- <kbd>Delete</kbd> clears the selected cells.
- **+ Row**, **Insert above** and **Delete rows** are above the grid.

## Trees

Plant Areas is a tree. Drag an item by its handle ⠿ to move it: drop on the top or bottom edge of a row to place it before or after, on the middle to put it inside. <kbd>Alt</kbd>+arrow keys indent, outdent and move an item. See [Plant Areas](help:plant-areas).

## Excel export and import

Every list has **Export .xlsx** and **Import .xlsx…**.

- The export is the saved list, with names in place of internal ids.
- **An import replaces the list with the file.** You first see what the file holds: how many rows are new, how many of the list are missing from the file and would be removed, and anything that could not be matched. Nothing changes until you confirm.
- Rows are matched by name (tag number, code or number), so things that refer to them still do. Renaming a row in the file makes it a new row.
- A file goes through the same rules as a save in the app. A file with a duplicate, a missing required value, or without a row that is in use elsewhere is refused, and the list is left as it was.

In the desktop app an export opens a Save As dialog. Exports are saved on your own PC.

## History

The **History** button on a list, an import, a symbol library, a template or a deliverable shows the changes made to that record: when, by whom, and the old and new values. The [Change log](help:change-log) shows the same for the whole project.

## Starting data and "Add missing"

Several lists start with ready-made data (cable types, motors, drives, starter charts, load factors, instrument types). On those lists a button such as **Add missing defaults** puts back any starting row that was deleted, without touching the rest.
