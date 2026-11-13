---
title: Template tags
group: Reference
order: 1
---
A cell of a load type's or an equipment type's rows can hold a tag in double angle brackets. When the row is written to a master list, the tag is replaced with data from the load, or from the runsheet row, it is written for.

```
<<path|modifier|modifier:arg>>
```

In a rows grid, typing `<<` offers the tags, a `.` after a link offers that record's fields, and `|` offers the modifiers. **All tags ⓘ** lists everything.

![The list of tags](img/template-tags.png)

Names are not case-sensitive, and ignore spaces and `_`.

## Tags of a load (load types)

| Tag | Filled with |
|---|---|
| `<<Tag>>`, `<<Description>>`, `<<Area>>`, `<<Rating>>`, `<<EquipType>>`, `<<Qty>>` | The load's own data, from the import or the Electrical Equipment List |
| `<<Units>>`, `<<Voltage>>`, `<<Phases>>` | The load's value, or else the load type's |
| `<<PlantArea>>`, `<<PlantAreaDesc>>` | The plant area the load is in |
| `<<LoadType>>`, `<<LoadTypeName>>`, `<<StdDrg>>`, `<<BucketType>>` | The load's load type |
| `<<SuppliedFrom>>`, `<<SuppliedFromDesc>>` | The panel it is supplied from, or Primary Supply |
| `<<Row>>` | 1, 2, … within the load's rows of that list |
| `<<CableCode>>`, `<<CableDesc>>`, `<<CableCores>>`, `<<CableVoltage>>` | The cable found in Cable Types for the load |
| `<<CableSize>>`, `<<CableInsulation>>`, `<<CableLength>>`, `<<CableParallel>>`, `<<CableConstruction>>` | The load's cable details from the Load List |
| `<<CableNo>>`, `<<Phase>>` | 1, 2, … and L1 / L2 / L3 / N / E, for each cable of a *Per power cable* row |
| Any Load List field, such as `<<starter_type>>` | That field of the load, calculated fields too |
| `<<Motor.…>>`, `<<Drive.…>>`, `<<Starter.…>>`, `<<LoadFactor.…>>` | The matched [motor](help:motor-data), [drive](help:drive-data), [starter](help:starter-coordination) and [load factors](help:load-factors) |
| `<<LoadType.CB.PartNumber>>` | A row of the load type's [component table](help:load-types#components) |

## Tags of a runsheet row (equipment types)

The columns of the [Instrument Runsheet](help:instrument-runsheet): `<<STD>>`, `<<Area>>`, `<<MECH>>`, `<<SUF>>`, `<<PID>>`, `<<VIA_MB>>`, `<<CONF>>`, `<<Rack>>`, and `<<#1>>`, `<<#2>>`, … for the number columns. A number column the row does not have fills in as nothing.

## Dot notation

Names joined by dots follow the row's links to other records and end on one of their fields. A path that ends on a record gives its name: a load's tag, a load type's code, a plant area's tag.

| From | Links | Example |
|---|---|---|
| A load | `LoadType`, `PlantArea`, `SuppliedFrom` (a load), `Eel` (its Electrical Equipment List item), `Cable` (the matched Cable Types row) | `<<SuppliedFrom.LoadType.Code>>` |
| A runsheet row | `EquipmentType` (→ `Package`), `PlantArea`, `Parent` (the load its parent tag names), `Rack` (→ `System`, `PlantArea`) | `<<Parent.PlantArea.Parent.Tag>>` |
| A plant area | `Parent` | `<<PlantArea.Parent.Parent.Tag>>` |
| An Electrical Equipment List item | `EquipmentCode`, `VendorPackage`, `SuppliedBy`, `InstalledBy`, `TerminatedBy`, `PlantArea`, `LoadType`, `Load` | `<<Eel.EquipmentCode.Name>>` |

## Modifiers

Modifiers come after `|` and are applied from left to right.

| Modifier | Effect | Example | Result |
|---|---|---|---|
| `upper`, `lower` | Capitals, or small letters | `<<LoadType.Name\|upper>>` | DIRECT ON LINE |
| `title` or `proper` | Each Word, keeping the [xProper](help:enums#xproper) words such as MCC and PLC | `<<Description\|title>>` | Feed Pump A |
| `trim` | Remove spaces at the ends | | |
| `nohyphen` | Remove hyphens | `<<Tag\|nohyphen>>` | P101 |
| `int` | Cut off the decimals | `<<Rating\|int>>` | 7 |
| `round:n` | Round to n decimals | `<<Rating\|round:1>>` | 7.5 |
| `dec:n` | Always n decimals | `<<Rating\|dec:2>>` | 7.50 |
| `pad:n` | Zero-pad to n digits | `<<#1\|int\|pad:3>>` | 007 |
| `left:n`, `right:n` | The first or last n characters | `<<Tag\|left:1>>` | P |
| `replace:a:b` | Replace a with b. Write `\:` for a colon | `<<Tag\|replace:-:_>>` | P_101 |
| `prefix:x`, `suffix:x` | Add text, only when the value is not blank | `<<Rating\|suffix: kW>>` | 7.5 kW |
| `default:x` | Use x when the value is blank | `<<Motor.Frame\|default:TBA>>` | TBA |

## When something does not match

- A **link the row does not have** (no load type allocated, no parent found) gives blank.
- A **name that is not a link or a field**, or an **unknown modifier**, leaves the tag as typed. It is listed, with what is wrong, in the warning above the master list.
