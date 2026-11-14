---
title: Distribution Panels
group: Project lists
order: 13
---
Distribution Panels holds the schedule of each distribution board: which circuit is on which way, its breaker and its load, with the loading of each phase worked out.

For a walk-through see [Build a distribution panel schedule](help:howto-panel-schedule).

![A panel shown as the switchboard](img/panel-switchboard.png)

## A panel

| Field | Meaning |
|---|---|
| **Panel** | The distribution panel of the Load List this schedule is for. Every active load supplied from it is a circuit to place. A panel can also be left unlinked, with a typed tag and typed circuits |
| **Title** | The schedule's title |
| **Type** | Three-phase or single-phase |
| **Ways** | An even number. Odd ways run down the left of the chassis and even ways down the right |

On a three-phase panel each way has a red, a white and a blue row (circuits QR1, QW1, QB1). On a single-phase panel a way is one row (Q1).

**+ Panel** adds a panel and **Delete panel** removes the selected one. A panel that a deliverable issues cannot be deleted.

## The figures at the top

Type these in:

| Box | Meaning |
|---|---|
| **Single Phase Voltage** | For example 240 |
| **Power Factor** | One power factor for the whole panel |
| **Isolator & Chassis Rating (Amps)** | |
| **Upstream CB Size (Min)** | |

These are worked out:

| Figure | How |
|---|---|
| kVA per phase | The watts on the phase ÷ power factor ÷ 1000 |
| Amps per phase | kVA × 1000 ÷ single-phase voltage |
| Maximum Amp | The largest phase amps |
| 3PH kW | All the watts ÷ 1000 |
| Remaining Capacity (Amps), % | The rating − Maximum Amp, and that as a share of the rating |
| Maximum kVA Rating | 3 × voltage × rating ÷ 1000 (single-phase: voltage × rating ÷ 1000) |

There is no diversity factor, and a line-to-line (two-pole) load is counted on one phase only.

## Circuits

Click a way to choose what is on it:

- **A load** supplied from the panel. A three-phase load takes a way's three rows.
- **A spare circuit breaker**, an **RCD RTS**, a **lighting control circuit**, or anything else you type.
- Nothing: a **spare space**.

**Place all** puts every load not yet on a way onto the first free ways.

For each pole row, type what the Load List does not hold: the **CB rating**, a **quantity** and the **watts each**. Left blank, the quantity is 1 and the watts come from the load's rating: a kW rating is shared equally by its poles, and an Amps rating is amps × voltage × power factor on each pole.

The notes under the panel say when a circuit's breaker is **smaller than its load current** (its watts ÷ the panel's voltage ÷ its power factor), as well as when a breaker or the upstream CB is larger than the isolator and chassis rating.

**+ Heading** adds a heading, such as "Lighting Contactor", that runs across the schedule above a pair of ways.

A load that is deleted, or moved to another panel in the Load List, stays on the schedule, marked, until you remove it. Nothing in the Load List is changed from here.

## Single line diagram

**Single line diagram** draws the panel from its schedule: the supply, the upstream breaker and isolator, the busbar, and a breaker and label for each circuit. **Switchboard** goes back.

![The same panel as a single line diagram](img/panel-sld.png)

## Saving, exporting and issuing

- Changes are a draft until **Save**.
- The Excel workbook has sheets Panels, Circuits (a row for each pole) and Headings. A circuit names its load by tag.
- A panel is issued as a [deliverable](help:deliverables) of type Distribution Panel: one row for each pole row, spare spaces included. The header figures are frozen with each revision.
