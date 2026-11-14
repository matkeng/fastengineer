---
title: Load Types
group: Project lists
order: 3
---
A load type is a kind of load: a DOL starter, a VSD, a feeder, a heater. Each load in the Load List is given one, and the load type holds the rows that a load of that kind adds to each master list. Load types are the templates of the power side of a project.

For a walk-through see [Set up Load Types and their template rows](help:howto-load-types).

![Load Types](img/load-types.png)

Click a row, or **Add load type**, to open the load type on a page of its own. **Save** on the page saves straight away; **‹ Load Types** goes back to the list, and asks first if there are changes that are not saved. While the page has unsaved changes, **Load Types** in the sidebar shows a dot, and you can look at another list and come back without losing them.

## Details

![A load type's details](img/load-type-details.png)

| Field | Rule |
|---|---|
| **Code** | Required. The short name loads are matched on, such as DOL |
| **Name** | Required. Unique |
| **kW or Amps** | Required: the unit of the rating range |
| **Voltage** | Required. A whole number |
| **Phases** | Required: AC-3-phase, AC-3-phase+N, AC-1-phase-LN, AC-1-phase-LL, DC or DC-mA |
| **From value**, **To value** | The rating range this type covers. Blank is an open end; both blank means any rating |
| **STD Drg**, **Bucket type**, **Load type**, **Field options** | Optional text, available to template rows as tags |
| **Multi load**, **Load qty** | Optional |
| **Starter chart** | The [Starter Coordination](help:starter-coordination) chart for loads of this type. Blank means the project default; *None* means no starter (a VSD, a feeder…) |
| **PDF** | One attached PDF, up to 50 MB, such as the standard drawing |

### Several types with one code

Several load types can share a code, for example three "DOL" types for three kW bands. Those with the same code and unit must have **From–To ranges that do not overlap**. Both ends are included, so 0–7.5 and 7.5–15 overlap and are refused: use 0–7.5 and 7.51–15.

Where a code is shared, drop-downs and workbooks show the range too: "DOL 0.37–11 kW".

### How a load gets its load type

In the [Load List](help:load-list), a load is given the load type whose **code** equals its load type text, whose **unit** is its load units, and whose **range includes its rating**. HP is converted to kW (× 0.7457) and blank units count as kW. A load whose code is known but whose rating is blank or outside every range is left without a load type, and named in a warning.

## The rows for each list

The tabs **Cable Schedule**, **Equipment List**, **Instrument List** and **PLC I/O List** hold the rows this load type adds to that master list. The number on a tab is how many rows it has.

![A load type's Cable Schedule rows](img/load-type-cable-rows.png)

Every load of this type adds these rows, with the `<<tags>>` replaced by that load's data. In the picture, a DOL load adds a power cable numbered `<<Tag>>-P…` from what it is supplied from to itself, and a control cable `<<Tag>>-C1`.

- The grid works like a spreadsheet and takes rows pasted from Excel.
- Type `<<` in a cell to pick a tag, or click one in the **Tags** list on the right: it goes in at the cursor of the cell you are editing, or at the end of the selected cell. The list can be searched, and its groups (the load, each linked record, this type's component tables, the modifiers) open on a click. A modifier is added to the tag the cursor is in. See [Template tags](help:template-tags).
- **Check**, below the grid, reads the tags as you type. A tag that is misspelt, follows a link that isn't there, or uses a modifier that doesn't exist turns its cell red and is listed with what is wrong; click it in the list to go to its cell. A tab shows ⚠ and how many of its tags match nothing.
- **Fill in from** chooses a load, and the rows are shown under the grid as they will be written for it: its tag, its panel, its cables. The loads of this type come first; any other load can be chosen and is filled in as if it were of this type. A row that repeats per cable shows a line for each cable (1.1, 1.2…). Nothing has to be saved first.
- On the Cable Schedule, the **Repeat** column set to *Per power cable* writes the row once for each of the load's power cables. See [Produce a cable schedule](help:howto-cable-schedule).
- **Export rows .xlsx** and **Import rows…** save and read this type's rows as a workbook.

![A load type's PLC I/O rows](img/load-type-io-rows.png)

## Components

The **Components** tab holds tables of parts that depend on the load: for example a **CB** table and a **Contactor** table.

![The Components tab](img/load-type-components.png)

- **+ Component table** adds a table. Give it a name.
- A table is **matched on** a field of the load: the Load rating by default, or any number or calculated field of the Load List, or the load's voltage, quantity, cable length or cable size.
- Its rows have a **Min** and a **Max**, then its own columns (Part Number, Manufacturer, Description by default; **+ Column** adds more).
- A load gets the **first row** whose Min ≤ its value ≤ Max. A blank Min or Max is an open end.

Template rows reach the row as `<<LoadType.CB.PartNumber>>`: the table, then the column. `<<LoadType.CB>>` is its first column, and `.Min` and `.Max` its range. A load with no value, or one that no row fits, gets blank; `|default:TBA` fills it.

## Clone, PDF and delete

- **Clone** opens a new load type with this one's details, rows, component tables and PDF, with the same code and named "… (copy)". Give it its own From–To range, then **Save**.
- **Attach PDF…** attaches a file. Once attached it can be opened (it is shown in the app), replaced, saved as a copy, or removed. The grid's PDF column opens it too.
- **Delete** removes the load type and its PDF. A load type that a person allocated to a load cannot be deleted until those loads are changed.

## Excel export and import

The workbook has a sheet for the list and one for each list's rows. A rows sheet left out of a file leaves those rows as they are. Rows sheets have a **Load type name** column, because codes can repeat. Attached PDFs are not in the workbook and stay with their load types.
