---
title: Load Factors
group: Project lists
order: 9
---
Load Factors holds load and demand factors by type of equipment, for working out running and demand loads.

![Load Factors](img/load-factors.png)

## A row

| Field | Meaning |
|---|---|
| **Equipment Type** | The kind of equipment, as the equipment list names it |
| **Plant Nameplate Load Factor** | |
| **Plant Optimised Load Factor** | |
| **Average Demand Factor** | |
| **Max Demand Factor** | |
| **Notes** | |

Every project starts with typical factors for 30 equipment types (nameplate 0.75, optimised 0.95, demand 1.00, with exceptions such as Air Conditioner 0.50 and Crane/Hoist 0.05 / 0.50), plus a **Default** row.

Click a row, or **Add row**, to edit. **Add missing typical rows** adds back starting rows that were deleted.

## How a load is matched

A load is matched on its **Equipment type** (a Load List field, usually from the MEL) to the row of the same name, ignoring capitals and extra spaces. A type that is not listed gets the **Default** row.

## Using the factors

| Tag | Value |
|---|---|
| `<<LoadFactor.NameplateLF>>`, `<<LoadFactor.OptimisedLF>>` | The load factors |
| `<<LoadFactor.AvgDemand>>`, `<<LoadFactor.MaxDemand>>` | The demand factors |
| `<<LoadFactor.EquipmentType>>` | The row that was used |
| `<<LoadFactor.Matched>>` | No when the Default row was used |
| `<<LoadFactor.Source>>` | Override, List or Default |
| `<<LoadFactor.Overridden>>` | Yes or No |

For example, a calculated field `<<rating>> * <<LoadFactor.NameplateLF>> * <<LoadFactor.AvgDemand>>` gives the average kW.

## Overriding the factors of one load

Any factor can be overridden on a row of the [Load List](help:load-list#load-factors):

- Click the row's **Load factors** cell. Each box shows the list's value. Type a value to use instead, or leave it blank to keep the list's.
- **Set load factors…** sets the ticked factors on every row the filters show.

![Setting load factors for the rows shown](img/load-set-factors.png)

An overridden value is shown in bold with ✎, and its tooltip gives the list value it replaces. Overrides apply everywhere the factors are used. They stay with the row when imports are read again, and are cleared with **Clear overrides**, or with the Load List's **Reset… → Load factor overrides**.
