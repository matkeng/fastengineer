---
title: Equipment Packages and Equipment Types
group: Project lists
order: 2
---
Equipment Packages lists the packages equipment is bought or supplied in. Each package can have **equipment types**, and an equipment type holds the template rows for an instrument assembly.

![Equipment Packages](img/equipment-packages.png)

## A package

| Field | Rule |
|---|---|
| **Package number** | Required. Unique in the list |
| **Description** | Required. Unique in the list |
| **Vendor name** | Optional. Several packages can share a vendor |
| **Package type** | Vendor, Client, SWR Supplier, Valves, Instrumentation, Large Mech, Installer or Other |

**Add package** adds one. Packages keep the order you put them in (↑ ↓), and the box at the top filters them.

## Equipment types

**+ Type** on a package's row adds an equipment type under it.

| Field | Rule |
|---|---|
| **Name** | Required. Unique across all packages |
| **Description** | Optional |
| **Package** | The drop-down moves the type to another package |

**⧉** duplicates an equipment type with its rows, as "… (copy)", straight after it.

A package that has equipment types cannot be deleted until they are moved or deleted. Types are saved together with the packages, with **Save**.

## The Lists of an equipment type

**Lists** on an equipment type opens its predefined rows for the four master lists: **Cable Schedule**, **Equipment List**, **Instrument List** and **PLC I/O List**. The button shows how many rows it has.

![The Lists of an equipment type](img/equipment-type-lists.png)

These are the rows the **Instrument generator** adds to the master lists: once for each row of the [Instrument Runsheet](help:instrument-runsheet) that names this equipment type, with the `<<tags>>` filled in from that row.

The tags offered are the columns of the runsheet: `<<STD>>`, `<<Area>>`, `<<MECH>>`, `<<SUF>>`, `<<PID>>`, `<<VIA_MB>>`, `<<CONF>>`, `<<Rack>>`, and `<<#1>>`, `<<#2>>`… Type `<<` in a cell to pick one. See [Template tags](help:template-tags).

**Export rows .xlsx** and **Import rows…** save and read one type's rows as a workbook, with a sheet for each list.

## Excel export and import

**Export .xlsx** and **Import .xlsx…** cover the packages and their equipment types together:

- The **Equipment Packages** sheet has one row for each equipment type, with its package's columns. A package with no types has a row of its own.
- Each list's rows are a further sheet ("Cable Schedule rows"…) with an **Equipment type** column. A rows sheet left out of a file leaves those rows as they are.

## Where packages are used

The [Electrical Equipment List](help:eel) names packages as **Vendor package**, **Supplied by**, **Installed by** and **Terminated by**. A package or type in use cannot be deleted.
