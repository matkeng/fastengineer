---
title: Set up Load Types and their template rows
group: How to
order: 5
---
Load types carry your standards: what a DOL starter, a VSD or a feeder needs in the cable schedule, the equipment list and the I/O list. Set them up once and every load of that type gets its rows.

## 1. Add the load type

1. Open **Project lists → Load Types** and press **Add load type**.
2. Fill in the **Code** (DOL), the **Name** (Direct on line motor starter), **kW or Amps**, **Voltage** and **Phases**.
3. If you have different standards for different sizes, give this one a **From value** and **To value**, for example 0.37 to 11, and make another type with the same code for the next band.
4. Choose a **Starter chart**, or *None* for a type with no starter.
5. Press **Save**.

![A load type's details](img/load-type-details.png)

## 2. Add its cable rows

1. Click the load type to open it, and choose the **Cable Schedule** tab.
2. Add a row for each cable a load of this type needs. For a DOL starter: a power cable and a control cable.
3. Type the cells, using tags for anything that differs from load to load. Type `<<` to pick a tag.

| Column | Power cable | Control cable |
|---|---|---|
| Repeat | Per power cable | |
| Cable Number | `<<Tag>>-P<<CableNo>>` | `<<Tag>>-C1` |
| From | `<<SuppliedFrom>>` | `<<SuppliedFrom>>` |
| From Description | `<<SuppliedFromDesc>>` | `<<SuppliedFromDesc>>` |
| To | `<<Tag>>` | `<<Tag>>` |
| To Description | `<<Description>>` | `<<Description>>` |
| Cable Type | Power | Control |
| Cores | 3C+E | 4C |

![The Cable Schedule rows of a load type](img/load-type-cable-rows.png)

You can paste a block of rows from Excel.

## 3. Add its other rows

- **Equipment List**: usually one row for the load itself, with `<<Tag>>`, `<<Description>>`, `<<Rating>>`, `<<Units>>`, `<<PlantArea>>`, `<<SuppliedFrom>>`.
- **PLC I/O List**: one row for each signal. For a DOL starter: `<<Tag>>-RUN` (DI), `<<Tag>>-FLT` (DI), `<<Tag>>-STRT` (DO).
- **Instrument List**: any instruments that always come with the load, such as a local control station.

![The PLC I/O rows of a load type](img/load-type-io-rows.png)

## 4. Add component tables, if parts depend on size

On the **Components** tab, press **+ Component table**, name it (for example *CB*), and add a row for each band: Min, Max, then the part number and description. A load gets the first row its rating falls in. Use it in a row as `<<LoadType.CB.PartNumber>>`.

For standard DOL starters you may not need this: the [Starter Coordination](help:starter-coordination) charts already give `<<Starter.CB>>`, `<<Starter.Contactor>>` and `<<Starter.Overload>>`.

## 5. Save and check

1. Press **Save**.
2. Open **Project master lists → Cable Schedule**. Every load of this type now has its rows.
3. Read the warning above the grid. A tag that matches nothing is named there, with the type it is on.

## 6. Make the variants

Open the load type and press **Clone**. The copy has the same code, rows and tables. Give it its own From–To range and name, change what differs, and **Save**.

## Sharing templates

**Export rows .xlsx** in a load type's form saves its rows as a workbook, with a **Tags** sheet listing what a cell can use. Edit it in Excel and bring it back with **Import rows…**, or use it in another project.

Reference: [Load Types](help:load-types), [Template tags](help:template-tags).
