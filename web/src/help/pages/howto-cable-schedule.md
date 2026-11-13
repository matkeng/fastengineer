---
title: Produce a cable schedule
group: How to
order: 6
---
The cable schedule is generated: each load adds the cable rows of its load type. Your part is the load types' rows and each load's cable details.

## 1. Give every load a load type and a supply

In **Project lists → Load List**, every load needs a **Load type** (which gives its cable rows) and a **Supplied from** (which gives the From end). See [Import a MEL and make the Load List](help:howto-import-mel#6-finish-the-load-list).

## 2. Enter the cable details

Cable sizing is done outside the app. Enter its results:

1. Filter the Load List to a group of loads with the same cable, for example by rating.
2. Press **Set cable details…**.
3. Tick and fill in the fields to set: **Power cable** (Multicore or Single core), **Parallel cables**, **Core size**, **Insulation**, **Earth cable size** (single core only) and **Cable length**.
4. Press **Set N row(s)**.

![Setting cable details for the rows shown](img/load-set-cable.png)

For one load, click its **Cable** cell.

To bring in many at once, export the Load List to Excel, fill in the cable columns, and import it. Only the cable and allocation columns are read back.

## 3. Make the power cable row repeat

In the load type's **Cable Schedule** rows, set **Repeat** to *Per power cable* on the power cable row. That row is then written once for each cable:

- **Multicore**: one row for each parallel cable. 1 × 70 mm² is one row; 2 × 50 mm² is two.
- **Single core**: for each parallel set, one row for each conductor (L1, L2, L3, and N for 3-phase+N) with cores `1C`, then one earth cable row.

Use `<<CableNo>>` in the cable number to tell them apart, and `<<Phase>>` for L1 / L2 / L3 / N / E.

A load type can have several repeating rows, for example the supply cable and the motor cable of a VSD.

## 4. Let the cable be looked up

For a repeating row, set the row's **Cable Type** (Power, VSD, Power Flex…) and **Cores** (3C+E, or `1C` for single core). The app finds the [Cable Types](help:cable-types) row with that type and cores and the load's size and insulation, and fills in the **Cable Type**, **Cable Code** and **Cores** cells.

Other cells can use the cable too: `<<CableSize>>`, `<<CableLength>>`, `<<CableDesc>>`, `<<CableVoltage>>`.

## 5. Check the master list

Open **Project master lists → Cable Schedule**.

![The Project Master Cable Schedule](img/master-cable-schedule.png)

Read the warning above the grid. Loads whose cable details are missing, or whose cable was not found in Cable Types, are named. Their rows are still written, with the cable cells blank.

If a cable is not found, check that Cable Types has a row with exactly that type, cores, size and insulation.

## 6. Issue it

1. Open **Deliverables** and make a **Cable Schedule** deliverable, or open the one you have.
2. To issue one area at a time, set **Only rows where** to the area column and its value.
3. Use **Choose and order…** to pick the columns.
4. Press **Issue Rev A…**.

See [Issue, compare and withdraw a revision](help:howto-issue-revision).
