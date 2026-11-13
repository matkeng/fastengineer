---
title: Instrument Types
group: Project lists
order: 16
---
Instrument Types lists the kinds of instrument loop: Level Transmitter, Density Transmitter, 2 x Conveyor Drift Switch and so on.

![Instrument Types](img/instrument-types.png)

## A type

| Field | Rule |
|---|---|
| **Instrument type** | Required. Unique |
| **P&ID function codes** | The function codes that make up a loop of this type. A Density Transmitter is `DE, DX, DIT`: element, source, transmitter. A code belongs to one type only |
| **Description** | Optional |

A project starts with common ISA types. Click a row, or **Add type**, to edit. **Add missing common types** adds back starting types that were deleted.

## What it is used for

On the [Loops](help:pid-symbols#loops) tab of PID Symbols, each loop is given an instrument type. The function codes are how the app suggests one: the type that shares the most codes with the loop's tags.
