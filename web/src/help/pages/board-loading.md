---
title: Board Loading
group: Project master lists
order: 3
---
Board Loading shows every switchboard, MCC and transformer of the project with the demand of the loads below it, against its own rating. It is worked out from the Load List each time it is shown, so there is nothing to set up or save.

## What counts as a board

A board is a Load List row marked as a **distribution panel**. The loads below it are the rows **supplied from** it, directly or through other boards. Boards are listed in supply order: a board, then the boards fed from it, indented.

## How the figures are worked out

For each load:

| Figure | How |
|---|---|
| **Connected kW** | Its rating. HP is converted. A rating in Amps or kVA is turned into kW through its voltage and power factor |
| **Max demand kW** | Connected kW × nameplate load factor × maximum demand factor |
| **Average kW** | Connected kW × nameplate load factor × average demand factor |
| **kVA** | kW ÷ power factor: the full-load power factor of the load's motor in [Motor Data](help:motor-data), or 0.85 when it has no motor |

The factors come from [Load Factors](help:load-factors) by the load's equipment type, or are the load's own where they were typed in on the [Load List](help:load-list).

A board's figures are the plain sums of its loads'. **There is no diversity between boards**: a main switchboard carries the full maximum demand of everything below it.

**Max demand A** is the kVA at the board's own voltage.

## Loading and spare

**Loading** is the board's maximum demand over its own rating, in the rating's unit:

- a board rated in **kVA** (a transformer) is compared on kVA
- a board rated in **kW** or HP is compared on kW
- a board rated in **Amps** (a switchboard, an MCC) is compared on amps

**Spare** is the rating less the demand, in the same unit. A board at or above the **Warn at** percentage (80 % to start with) is marked ⚠. A board with no rating still shows its totals, with a note that its loading can't be worked out.

## Loads that are not counted

A load with no rating, with units that are not kW, HP, Amps or kVA, or rated in Amps with no voltage adds nothing. Each board says how many of its loads were not counted, and the list under the table names them with the reason. Deleted loads are never counted.

## Export

**Export .xlsx** saves the table, the loads not counted and these rules as a workbook.

For totals of your own design (by area, by load type, with your own formulas) use the [Load List Summary](help:load-summary).
