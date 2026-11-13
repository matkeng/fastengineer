---
title: List import: calculated columns
group: Screens
order: 22
---
A calculated column is worked out for every row from the other columns, like a formula in a spreadsheet.

![A calculated column](img/import-calculated.png)

## Adding one

1. On the **Calculated** tab press **Add calculated column** and type its **Column name**.
2. Fill in the conditions and values (below).
3. The **Preview** underneath shows the result for every row, and how many rows gave an error.

Columns run from top to bottom, so one can use the result of another above it. ↑ ↓ reorder them and ✕ removes one.

## Conditions and values

Conditions are checked in order:

- **If** … **then**: when the condition holds, the row gets this value.
- **+ Else if** adds further conditions, each with its own value. The first one that holds gives the value.
- **Else**: the value for a row where no condition holds.
- **On error**: the value when a condition or value cannot be worked out for a row, for example a blank compared with a number.
- **NOT** beside a condition uses its opposite.

A column is written `<<Column name>>`. **Insert a column…** adds one to the box you were last in.

- A value that looks like a number is a number. Other values are text.
- Text needs no quotes in a comparison of a column: `<<Type>> == 'Pump'`.
- Plain text in a value box, such as `Motor`, is used as it is.

### Examples

| Purpose | If | then | Else |
|---|---|---|---|
| A size band | `<<kW>> >= 30` | `Large` | `Small` |
| kW from HP | `True` | `round(<<Motor HP>> * 0.746, 1)` | |
| Mark deleted rows | `<<Strike through>> == 'Full Row'` | `Yes` | `No` |
| A tag without its hyphen | `True` | `<<Tag>>.replace('-', '')` | |

## The functions you can use

**Show the functions you can use** opens a list of every function, grouped (columns and values, comparisons and logic, numbers, text), each with an example and its result on a sample row. Type in the search box to narrow the list. Click an example to put it into the box you were last in.

![The list of functions](img/import-functions.png)

In short:

- **Operators**: `+ - * / // % **`, comparisons `== != < <= > >=`, `in`, `not in`, `and`, `or`, `not`, and `x if condition else y`.
- **Number functions**: `abs`, `round`, `int`, `float`, `min`, `max`, `ceil`, `floor`, `sqrt`, `exp`, `log`, `log10`, `sin`, `cos`, `tan`, `degrees`, `radians`, `trunc`.
- **Text functions**, written after a text value: `.upper()`, `.lower()`, `.title()`, `.capitalize()`, `.strip()`, `.replace()`, `.startswith()`, `.endswith()`, `.split()`, `.find()`, `.count()`, `.zfill()`, `.ljust()`, `.rjust()`, `.isdigit()`, `.isalpha()`; and `len()`, `str()`, `proper()`.

`.title()` and `proper()` put text into proper case and keep the words of the project's [xProper list](help:enums#xproper) as written, so "mcc-01 feed" becomes "MCC-01 Feed".

## Only these can be used

Anything that is not on the list is refused before it runs, and the preview reports it as **Not allowed**. An import with such a formula cannot be saved; the message names the column and the box.
