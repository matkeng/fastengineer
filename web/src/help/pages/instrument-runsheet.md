---
title: Instrument Runsheet
group: Project lists
order: 14
---
The Instrument Runsheet is what the **Instrument generator** runs from. One row is one instrument assembly: an equipment type, in an area, on a piece of parent equipment. Each row adds its equipment type's rows to the master lists.

For a walk-through see [Generate instrument and I/O rows](help:howto-instruments).

![The Instrument Runsheet](img/instrument-runsheet.png)

## The columns

| Column | Tag | Rule |
|---|---|---|
| Equipment Type Ref | `<<STD>>` | Required. The name of an [equipment type](help:equipment-packages) |
| Area Ref | `<<Area>>` | Required. A plant area's tag number |
| Parent Equipment Ref | `<<MECH>>` | Required. A tag in the Electrical Equipment List or the [MEL](help:mel-list) |
| Name Suffix | `<<SUF>>` | Text |
| PID | `<<PID>>` | Text |
| IO via MARSHALLING BOX | `<<VIA_MB>>` | Text |
| Confirmed | `<<CONF>>` | TRUE or FALSE. Blank is FALSE |
| PLC Rack Num | `<<Rack>>` | Text. A rack tag of the [PLC List](help:plc-list) links to that rack |
| #1, #2, … | `<<#1>>`, `<<#2>>`, … | Text, kept exactly as typed. Use them for loop numbers, ranges, anything the template rows need |

The tag under each heading is what an equipment type's rows use to pick up that column.

## Editing

The grid works like a spreadsheet and takes rows pasted from Excel. **+ Row**, **Insert above** and **Delete rows** are above it.

- **The three references must match** for the list to be saved (ignoring capitals and extra spaces). A cell that matches nothing is marked as you type, with the reason, and **Save** stays off until it is fixed.
- Rows may repeat, and keep their order. A row with nothing in it is dropped.
- The grid starts with #1 to #35. **+ 5 # columns** adds more, and so does pasting rows that are wider. Once saved, the list has as many number columns as its widest row uses (35 at least, 500 at most).

## Confirmed

Unconfirmed rows still add their rows to the master lists, marked FALSE in the **Confirmed** column. A deliverable can filter on it to issue only confirmed rows.

## Renaming and deleting what a row refers to

The equipment type and the area are kept by identity: renaming one changes nothing here, and one that a row uses cannot be deleted. The parent is kept as its tag.

## Excel export and import

One sheet with these headings, with as many # columns as the list has. An import replaces the rows and goes through the same must-match rule.
