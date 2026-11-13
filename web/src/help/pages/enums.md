---
title: Enums
group: Project lists
order: 18
---
Enums are the choice lists that other lists pick from. They are edited per project, together, and saved with **Save**.

![Enums](img/enums.png)

## The five enums

| Enum | A project starts with | Used by |
|---|---|---|
| **Disciplines** | E Electrical, I Instrumentation, M Mechanical, P Piping, C Civil, S Structural, H HVAC, PR Process, G General | Equipment Codes, Drawing List, Document List |
| **Drawing types** | Single Line Diagram, Schematic, Termination Diagram, Loop Diagram, Block Diagram, Layout, P&ID, Panel Schedule… | Drawing List |
| **Document types** | List, Schedule, Datasheet, Index, Register, Calculation, Specification, Report, Other | Document List |
| **Drawing statuses** | Draft, IFR, IFA, IFT, IFC, AB, Superseded, Cancelled | Drawing List, Document List |
| **xProper** | MCC, PLC, VSD, DOL, HMI, UPS, SCADA, RTD, I/O, P&ID, LV, MV, HV… | Proper case |

## Editing

- An item has a **code** and a **name**. A discipline needs a code; for the others it is optional, and an item is shown by its code when it has one.
- Codes are unique, and names are unique within an enum.
- **+ Add** adds an item, ↑ ↓ reorder, and ✕ removes one.
- An item that a drawing, a document or an equipment code uses **cannot be removed**. The count of uses is shown beside it. Renaming it is fine, and the lists follow.

## xProper

xProper is a plain list of words that must keep their capitals when text is put into proper case.

Proper case gives each word a capital first letter and makes the rest small. Then each xProper word is put back **exactly as written** wherever it appears as a whole word, whatever its case: "mcc-01 feed to plc i/o" becomes "MCC-01 Feed To PLC I/O". Digits next to a word are fine, so adding "kW" turns "7.5KW" into "7.5kW".

It applies wherever proper case is used:

- the `title` and `proper` modifiers of [template tags](help:template-tags#modifiers), as in `<<Description|title>>`;
- `.title()` and `proper()` in [calculated columns](help:import-calculated), calculated fields and summary tables.
