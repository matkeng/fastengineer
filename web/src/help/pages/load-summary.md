---
title: Load List Summary
group: Project master lists
order: 2
---
The Load List Summary Page holds tables that total up the Load List: the loading of a transformer, the connected kW of each MCC, the number of drives by area. You define the tables; they are worked out from the Load List whenever they are shown.

![Editing a summary table](img/load-summary-edit.png)

## Making a table

1. Press **Edit tables**, then **+ Table**, and give the table a name.
2. Fill in its filter, rows and columns (below).
3. Press **▶ Preview** to work the tables out without saving.
4. Press **Save**.

**Export .xlsx** saves the tables, a sheet for each.

## The parts of a table

### Filter

Which active loads the table looks at. Blank means all. For example, to leave out panels and spares:

```
not <<ispanel>> and <<loadtype>> != 'SPARE'
```

### Rows

Each row is typed in: a **name**, a **condition** choosing its loads among the filtered ones, and optionally a **reference load** (a tag) whose own values the formulas can use as `<<Ref.load_rating>>`.

| Row for | Condition |
|---|---|
| Everything fed from TX-1, directly or through the MCCs below it | `'TX-1' in <<supplychain>>` |
| MCC-1's own loads | `<<suppliedfrom>> == 'MCC-1'` |
| One plant area | `<<plantarea>> == '100'` |

`<<supplychain>>` lists the panels a load is fed from, nearest first. That is what makes a transformer's loading one condition.

### Columns

Columns are added in order with **+ Total column** or **+ Formula column**.

- A **total of a field**: Sum, Count, Min, Max or Average of any Load List field (calculated ones too), or the rating, voltage, quantity or cable length, over the row's loads. A column can have its own condition, to count only some of them. Blanks and text are left out.
- A **formula** over the row's other columns by name, such as `<<Total kW>> / <<Ref.load_rating>> * 100` for a transformer's loading in per cent. It can also use `<<Row>>` and `<<Loads>>`. Like a calculated field it has Applies when, Otherwise, decimals and checks (**+ Check**).

### Total row

Tick **Total row** for a last row over every load the filter lets in.

## Reading a table

The **Loads** column says how many loads a row has. Hover over it for their tags. A cell whose formula cannot be worked out, or that fails a check, is marked ⛔ or ⚠.
