---
title: Load List
group: Project master lists
order: 1
---
The Project Master Load List is every load of the project in one live list: the rows of every MEL and EEL import, through their saved rules, plus the items of the Electrical Equipment List. Everything on the power side is generated from it.

![The Project Master Load List](img/load-list.png)

## What you see

Each row is a load, with its **Status**, its **Source** (the import, or the Electrical Equipment List), its **Tag** and **Description**, and then the mapped fields of the import as read-only columns. The line above the grid counts the rows that still have no plant area, no load type or no supply.

Four things are set here, and saved as soon as you choose:

| Column | Choice |
|---|---|
| **Plant area** | One of the [Plant Areas](help:plant-areas) |
| **Load type** | One of the [Load Types](help:load-types) |
| **Distribution panel** | Tick it for a load that supplies others |
| **Supplied from** | Primary Supply, or one of the list's distribution panels |

Rows of the Electrical Equipment List show these read-only: they are set in [that list](help:eel).

### Filled in automatically

Values in *italics* were filled in from the import:

- the **plant area**, when the row's area text equals exactly one plant area's tag number;
- the **load type**, when its load type text equals a load type's code and its rating is in that type's range (see [Load Types](help:load-types#how-a-load-gets-its-load-type));
- **distribution panel** and **supplied from**, from the import's "is a load centre" and "supplied from" fields.

They follow the import until a person chooses a value. A value a person chose is never changed automatically.

### Setting many rows at once

Filter the grid to the rows you want, then use the buttons above it: **Set plant area…**, **Set load type…**, **Set supplied from…**, **Set cable details…**, **Set load factors…**. Each sets the value on every row the filters show.

### Rules

- A row cannot be supplied from itself, and panels cannot feed each other in a loop.
- A panel cannot stop being a panel while loads a person pointed at it are supplied from it.
- A plant area or load type that a person allocated cannot be deleted from its list until those rows are changed.

## Deleted rows

Rows are remembered by import and key. A row that leaves its import (or whose import is deleted, or whose file marks it deleted) **stays in the list, marked Deleted**, with its allocations. If it comes back, it gets them back. Deleted rows are left out of the master lists and deliverables.

## Cable details

Cable sizing is done outside the app. Click a load's **Cable** cell, or use **Set cable details…** for every row shown, and enter:

![Setting cable details](img/load-set-cable.png)

| Field | Choices |
|---|---|
| **Power cable** | Multicore or Single core |
| **Parallel cables** | How many cables in parallel |
| **Core size** | A size from the Cable Types list |
| **Insulation** | An insulation from the Cable Types list |
| **Earth cable size** | For single-core cables only |
| **Cable length** | In metres |

These pick the load's cable from [Cable Types](help:cable-types#how-a-load-s-cable-is-chosen) and are available to template rows as tags.

## Load factors

The **Load factors** cell shows the load's four factors from the [Load Factors](help:load-factors) list (NLF / OLF / Avg / Max). Click it to override any of them for this load.

## Fields

**Edit fields…** renames, adds, deletes and reorders the fields of the Load List for the project, and sets each one's kind: text, number, yes/no or calculated.

![Editing the fields of the Load List](img/load-fields.png)

- Every field has a **key that never changes**. It is what import mappings and `<<tags>>` use, so renaming a field changes only the name people see. A new field's key is made from its name: Motor HP → `<<motor_hp>>`.
- A deleted field is taken out of every import's mapping, so its values stop coming through.
- The fields the app itself reads (marked with a lock: Tag, Description, Area, Equipment type, Quantity, Load units, Load rating, Voltage, Phases, Load type, Is a load centre, Supplied from, Deleted) can be renamed and moved, not deleted.
- **Save…** first shows what the change will do; **Confirm and save** makes it.

### Calculated fields

A calculated field is worked out for every row, like a spreadsheet formula that refers to other cells of the row. Press **+ Add calculated field**, name it, then **ƒ Formula…**.

![A calculated field's formula](img/load-calculated-field.png)

| Part | Meaning |
|---|---|
| **Applies when** | A condition for the rows the field is relevant to. Blank means every row |
| **Otherwise** | The value for the other rows. Blank means nothing |
| **Formula** | One expression. `<<key>>` is a cell of the row |
| **Decimals** | A number answer is rounded to this many |
| **Checks** | Expressions that hold for a good answer, with `<<value>>` the answer, each an *error* or a *warning* with a message. For example `0 < <<value>> <= 1` |

**Insert a reference…** lists everything a formula can use: any Load List field, another calculated field, the load's cable (`<<cable_length>>`, `<<cable_size>>`…), and what the app works out (`<<units>>`, `<<voltage>>`, `<<phases>>`, `<<loadtype>>`, `<<plantarea>>`, `<<suppliedfrom>>`…), as well as the matched motor, drive, starter and load factors.

The functions and operators are those of [calculated columns](help:import-calculated#the-functions-you-can-use). A blank cell is `''`, so write `(<<field>> or 0)` to count it as 0.

**▶ Try it on the Load List** works the formula out for every active row before you save, problems first.

In the Load List a calculated column is marked ƒ. A cell with a problem shows ⛔ (error) or ⚠ (warning), with what is wrong as its tooltip. Calculated fields are worked out in the order they use each other, and a loop is refused. A field that a calculation uses cannot be deleted.

See [Add calculated fields and summary tables](help:howto-calculated-fields) for worked examples.

## Reset

**Reset…** forgets what has been set on the Load List. A dialog asks what to reset and must be confirmed.

![Resetting the Load List](img/load-reset.png)

- **Everything**: every remembered row is forgotten, with the plant areas, load types, panels, supplies and cable details people set, and the rows kept as deleted. The list is built again from the imports.
- **Only these**: the rows stay, and what you tick is cleared on all of them.

Either way the imports are read again afterwards, so whatever their latest files give is filled in automatically. The import files, rules and mappings are not touched. **It cannot be undone**; the change log records it.

## Export and import

**Export .xlsx** saves the list. **Import .xlsx…** reads back only the plant area, load type, distribution panel, supplied from and cable columns, matched by Source and Key. A file never adds or removes rows: they come from the imports. A change that breaks a rule is refused for that row and reported.

**Refresh** reads the imports again.
