---
title: Cable Schedule, Equipment, Instrument and IO lists
group: Project master lists
order: 3
---
The four project master lists are worked out by the two [generators](help:generators):

| Master list | Deliverable made from it |
|---|---|
| Project Master Cable Schedule | Cable Schedule |
| Project Master Equipment List | Equipment List |
| Project Master Instrument List | Instrument List |
| Project Master IO List | PLC I/O List |

![The Project Master Cable Schedule](img/master-cable-schedule.png)

## Where the rows come from

- **Power**: every active load of the [Load List](help:load-list) adds the rows its [load type](help:load-types) has for the list, in tag order, with the tags filled in from that load.
- **Instrument**: every row of the [Instrument Runsheet](help:instrument-runsheet) adds the rows its [equipment type](help:equipment-packages) has for the list, filled in from that row.

The line under the title counts the rows from each.

A master list is **worked out when it is opened**, so it is always up to date and there is nothing to run. It is **read only**: to change a row, change the Load List, the load type, the equipment type or the runsheet.

Besides the list's own columns each row has **Generator** (Power or Instrument) and **Confirmed** (the runsheet row's; a load's rows are always TRUE).

## Warnings

A yellow line above the grid lists anything that needs attention:

- a load with **no load type** adds no rows;
- a **tag that matches nothing** is left in the text as typed;
- a load whose **cable** could not be found in Cable Types has blank cable cells.

## Columns

**Edit columns…** renames, adds, deletes and reorders the columns of all four master lists for the project.

![Editing the columns of the master lists](img/master-columns.png)

**Save…** first shows what the change will do, then **Confirm and save** makes it in one go:

- a **rename** moves the cells of every load type's and equipment type's rows to the new name, and renames the column in the deliverables made from the list;
- a **delete** drops those cells and takes the column out of those deliverables.

Some columns can be moved but not renamed or deleted (marked with a lock): **Tag** (**Cable Number** on the Cable Schedule), which revisions are compared by, and the Cable Schedule's **Cable Type**, **Cores** and **Cable Code**, which per-cable rows fill in.

Issued revisions keep the columns they were issued with. The first revision after a rename shows the old column removed and the new one added.

## The starting columns

| List | Columns |
|---|---|
| Cable Schedule | Cable Number, From, From Description, To, To Description, Cable Type, Cable Code, Cores, Size, Voltage, Length (m), Route, Remarks |
| Equipment List | Tag, Description, Equipment Type, Plant Area, Rating, Units, Voltage, Phases, Supplied From, Manufacturer, Model, Remarks |
| Instrument List | Tag, Description, Instrument Type, Plant Area, Service, Signal, IO Type, Range, Units, Remarks |
| IO List | Tag, Description, Signal, IO Type, PLC System, Rack, Slot, Channel, Plant Area, Remarks |

## Exporting and issuing

**Export .xlsx** and **CSV** save the list as it is now. To issue it with a revision letter, make a [deliverable](help:deliverables) from it; **Deliverables** goes there.

![The Project Master IO List](img/master-io-list.png)
