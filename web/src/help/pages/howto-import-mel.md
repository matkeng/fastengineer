---
title: Import a MEL and make the Load List
group: How to
order: 1
---
This takes a mechanical equipment list (MEL) from Excel or CSV to a Load List in which every load has a plant area and a load type.

## Before you start

Two lists make the automatic allocation work. Set them up first if you can:

- [Plant Areas](help:plant-areas), using the same area numbers as the MEL.
- [Load Types](help:load-types), with codes that the MEL's starter or drive column can be turned into (DOL, VSD, FEEDER…).

## 1. Create the import and upload the file

1. Open **List import**.
2. Type a name, such as *Plant MEL*, leave the kind as **MEL → load list**, and press **Create**.
3. Under **Files**, choose **From Excel…** and pick the workbook, the sheet, the header row and the key column with the [Excel table wizard](help:excel-wizard). For a CSV, choose **CSV file**.
4. The **key column** is the equipment tag. Press **Upload**.

![An import with its first file](img/import-overview.png)

## 2. Tidy the table

Work through the tabs from left to right. Skip any you do not need.

1. **Columns**: untick the columns you do not need; rename any with awkward names.
2. **Rows**: untick the rows that are not electrical loads (tanks, chutes, manual valves). Give a reason for anything the mechanical engineer might question.
3. **Overrides**: click a cell that is wrong and type the right value with a reason.
4. **Custom rows**: add a load the MEL is missing.

![Unticking a row that is not a load](img/import-rows.png)

Details: [the rules](help:import-rules).

## 3. Make the columns the Load List needs

The MEL rarely has your load type codes. Make them:

- With **Find Replace**, when one column says it in other words. Read the *Starter* column and replace `Direct On Line` with `DOL`, `Variable Speed` with `VSD`.
- With a **Calculated** column, when it depends on more than one thing: If `<<Type>> == 'Pump' and <<kW>> > 75` then `SOFT`, Else `DOL`.

To mark struck-through rows as deleted, add a calculated column: If `<<Strike through>> == 'Full Row'` then `Yes`, Else `No`.

## 4. Map the columns

On the **Mapping** tab, press **Suggest mapping for unmapped fields**, then check each field:

- **Tag**, **Description**, **Area**
- **Load rating** and **Load units** (kW, HP or A)
- **Voltage**
- **Load type**: the column you made in step 3
- **Equipment type**: used for load factors
- **Deleted**: the column from the strike-through rule

![Mapping the columns](img/import-mapping.png)

Details: [mapping](help:import-mapping).

## 5. Check and save

1. Open the **Result** tab and switch to **Load list** to see exactly what will go into the Load List.
2. Press **Save**.

## 6. Finish the Load List

1. Open **Project lists → Load List**.
2. Look at the line above the grid: *n without a plant area · n without a load type · n without a supply*.
3. Filter the **Plant area** column to blank, and choose the areas, or use **Set plant area…** for all the rows shown. Do the same for **Load type**.
4. Tick **Distribution panel** on the switchboards and MCCs, then set **Supplied from** on the loads, using **Set supplied from…** on filtered rows.

![The Load List](img/load-list.png)

Switchboards that are not in the MEL are entered in the [Electrical Equipment List](help:eel).

## Next

- [Take in a revised MEL](help:howto-revised-mel)
- [Set up Load Types and their template rows](help:howto-load-types)
