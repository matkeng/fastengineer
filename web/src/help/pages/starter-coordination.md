---
title: Starter Coordination
group: Project lists
order: 8
---
Starter Coordination holds Type 2 coordinated direct-on-line starter selections by motor kW: the circuit breaker, contactor and overload relay that go together.

![Starter Coordination](img/starter-coordination.png)

## The starting data

Every project starts with **NHP's six Type 2 coordination charts** (126 rows, as printed in NHP TD-001-EN), at 400/415 V with Terasaki ZS earth leakage circuit breakers:

| Chart | Fault level | Contactor | Overload |
|---|---|---|---|
| ECH54.2 | 50 kA | Sprecher+Schuh CA7/CA9 | CEP7-1EF electronic |
| ECH54.12 | 50 kA | Sprecher+Schuh CA7/CA9 | E300 (EtherNet/IP) |
| RECH54.23 | 50 kA | Allen-Bradley 100-C/100-E | E300 (EtherNet/IP) |
| ECH64.2 | 65 kA | Sprecher+Schuh CA7/CA9 | CEP7-1EF electronic |
| ECH64.13 | 65 kA | Sprecher+Schuh CA7/CA9 | E300 (EtherNet/IP) |
| RECH64.24 | 65 kA | Allen-Bradley 100-C/100-E | E300 (EtherNet/IP) |

Each row has the chart, its fault level, the motor kW and FLC, the circuit breaker and its amps, the earth leakage setting range, the contactor, the overload relay and its setting range, the instantaneous trip amps, the minimum trip as a multiple of FLC, and the chart's note.

> The selections are transcribed from the manufacturer's charts. Check them against the current charts before using them for design or purchasing.

## Choosing the chart

- **Project default chart**, at the top of the list, is the chart used unless a load type says otherwise. It starts as ECH64.2 (65 kA).
- Each [load type](help:load-types) has a **Starter chart**. Blank means the project default. *None* means no starter, for a VSD or a feeder.

## How a load gets its starter

A load gets its chart's row for **the smallest motor at least its kW**. HP is converted. A rating in Amps is matched on the chart's FLC. A load above 75 kW gets none.

## Using the starter's data

| Tag | Value |
|---|---|
| `<<Starter.CB>>` | Circuit breaker |
| `<<Starter.Contactor>>` | Contactor |
| `<<Starter.Overload>>`, `<<Starter.Range>>` | Overload relay and its setting range |
| `<<Starter.ELSetting>>` | Earth leakage setting range |
| `<<Starter.InstTrip>>`, `<<Starter.MinTrip>>` | Instantaneous trip, and minimum trip × FLC |
| `<<Starter.Chart>>`, `<<Starter.FaultkA>>` | The chart used and its fault level |

## Editing

Click a row, or **Add row**, to edit. **Add missing NHP charts** adds back starting rows that were deleted. The Excel export has a "Settings" sheet that holds the default chart.
