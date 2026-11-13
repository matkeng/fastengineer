---
title: List import: mapping
group: Screens
order: 23
---
Mapping says which column of the table fills which field of the list. It is the last step of the recipe.

![The Mapping tab](img/import-mapping.png)

## Mapping a field

For each field, either:

- choose a column under **Comes from** (the file's columns after the Columns step, and any text, find/replace or calculated columns), or
- type a **Fixed value** to give every row the same value.

A field left as *(not mapped)* is left out of the list.

**Suggest mapping for unmapped fields** fills in the fields whose names match a column. Check what it chose.

## The fields of a load list

A MEL, ELL, EEL or LIL import maps onto the fields of the project's Load List. These are the ones the app itself reads:

| Field | Used for |
|---|---|
| Tag | The load's tag. When it is not mapped, the import's key is used |
| Description | Shown beside the tag everywhere |
| Area | When it equals a plant area's tag number, the load's plant area is filled in |
| Equipment type | Matches the load to a row of [Load Factors](help:load-factors) |
| Quantity | |
| Load rating, Load units | The rating and whether it is kW, HP or Amps. Blank units count as kW |
| Voltage, Phases | Used in place of the load type's when given |
| Load type | When it equals a load type's code and the rating is in its range, the load type is filled in |
| Is a load centre | Yes makes the load a distribution panel |
| Supplied from | A panel's tag: what the load is supplied from |
| Deleted | Yes marks the load deleted in the Load List |

Other fields (Poles, Drive duty, Drive enclosure, Starter type and any you add) are carried into the Load List, where template rows and calculated fields can use them.

**Edit the Load List fields…** renames, adds, deletes and reorders the fields for the whole project. See [Load List](help:load-list#fields).

## Numbers and yes/no fields

- A field of kind *number* that gets a value which is not a number keeps it as text, and a warning counts them.
- A *yes/no* field reads Yes, Y, True, 1 and X as yes (in any case). Anything else is no.

## Other kinds of import

A **PIL** import maps onto instrument-list fields (tag, loop, instrument type, signal type…), and a **PSL** import onto the [PID Symbols](help:pid-symbols) fields. The first file sent from Symbol detection to a PSL import maps its columns by itself.
