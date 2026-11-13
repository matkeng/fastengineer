---
title: Share settings and lists with another project
group: How to
order: 11
---
Projects do not share data, so standards are passed from one to another as files.

## An import's rules

To give a colleague the recipe of a list import:

1. Open the import, **Save** or **Discard** any changes, and press **Export settings**. It saves a `.json` file with the column rules, hidden rows, text columns, overrides, added rows, find/replace and calculated columns, mapping and reasons. The uploaded files are not in it.
2. In the other project, in **List import**, press **New from settings…** and choose the file. A new import is made with the file's name and settings. Then upload its file.

To replace the rules of an existing import, open it and press **Import settings…**. The settings arrive as unsaved changes: **Save** keeps them, **Discard** brings the old ones back. The file must be for the same kind of list.

Rules that name a key or column the receiving file does not have are listed under *rules not applied* on the Overview.

## A list

Every project list has **Export .xlsx** and **Import .xlsx…**:

1. In the first project, open the list and press **Export .xlsx**.
2. In the other project, open the same list and press **Import .xlsx…**. Read what the file would add and remove, then confirm.

An import **replaces** the list with the file. Import the lists others refer to first: Plant Areas, Equipment Packages and Enums before the lists that use them.

## Load types and equipment types

- The **Load Types** workbook holds every load type with its rows and component tables. Attached PDFs are not in it.
- **Export rows .xlsx** in one load type's form, or in an equipment type's **Lists**, saves just that type's rows, with a **Tags** sheet. **Import rows…** reads it into another type, here or in another project.

## A symbol library

In **Symbol detection**, open the library's **Settings** and press **Export…**. In the other project press **Import…** under the library box. The file holds the tag rules, the ignored words and areas, and the templates. Drawings are not in it.

## Starting a new project from an existing one

An administrator can create a project that starts with a copy of an existing project's standards (its symbol libraries and card and rack types). The project lists start empty: bring them across with their workbooks, as above.
