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

Each row has the chart, its fault level, the motor kW and FLC, the circuit breaker and its amps, the earth leakage setting range, the contactor, the overload relay and its setting range, the instantaneous trip amps, the minimum trip as a multiple of FLC, the **voltage** the row is for (400 for NHP's charts), and the chart's note.

> The selections are transcribed from the manufacturer's charts. Check them against the current charts before using them for design or purchasing.

## Choosing the chart

- **Project default chart**, at the top of the list, is the chart used unless a load type says otherwise. It starts as ECH64.2 (65 kA).
- Each [load type](help:load-types) has a **Starter chart**. Blank means the project default. *None* means no starter, for a VSD or a feeder.

## How a load gets its starter

A load gets its chart's row for **the smallest motor at least its kW**. HP is converted. A rating in Amps is matched on the chart's FLC. A load above 75 kW gets none.

Only rows **for the load's voltage** are considered. Voltages are grouped in ranges: 200-240, 380-415, 440-480, 550-600 and 660-690 V. A 400 V row serves a 380 to 415 V load. A 690 V or 240 V load gets no row from NHP's 400/415 V charts. To cover another voltage, add your own rows with that **Voltage**; the same chart name can have rows for several voltages.

## Warnings

A calculated field of the [Load List](help:load-list) that uses the starter (`<<Starter.…>>`) shows ⚠ when:

- **No starter is matched**: the load's chart has no row for its voltage, for example *chart ECH64.2 is for 380-415 V, the load is 690 V*.
- **The motor's full load current is outside the overload's setting range**: the overload could not be set to the motor's current. The current is the one in [Motor Data](help:motor-data), taken at the load's voltage.

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
