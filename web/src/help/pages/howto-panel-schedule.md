---
title: Build a distribution panel schedule
group: How to
order: 8
---
A panel schedule is built from the loads the Load List says are supplied from the panel.

## 1. Make sure the panel and its loads are in the Load List

1. The panel itself must be a load with **Distribution panel** ticked. Panels that are not in the mechanical equipment list are entered in the [Electrical Equipment List](help:eel).
2. Each load on the panel must have the panel as its **Supplied from**.

## 2. Add the panel schedule

1. Open **Project lists → Distribution Panels** and press **+ Panel**.
2. Choose the **Panel** of the Load List it is for, and type a **Title**.
3. Choose the **Type** (three-phase or single-phase) and the number of **Ways**.
4. Type the **Single Phase Voltage**, **Power Factor**, **Isolator & Chassis Rating** and **Upstream CB Size**.

## 3. Place the circuits

Press **Place all** to put every load supplied from the panel on the first free ways. Then arrange them:

- click a way to change what is on it, or to move a load there;
- a three-phase load takes a way's three rows; a single-phase load one row;
- for ways with no load, choose a spare circuit breaker, an RCD, a lighting control circuit, or type your own.

![The switchboard view](img/panel-switchboard.png)

## 4. Enter breakers and watts

On each pole row, type the **CB rating**. For lighting and power circuits, type the **quantity** and **watts each**. Leave them blank on a load from the Load List and its rating is used.

Add a **+ Heading** above a group of ways, such as "Lighting Contactor".

## 5. Check the loading

The figures at the top update as you go: kVA and amps on each phase, the maximum amps, the total kW, and the remaining capacity in amps and per cent. Move single-phase circuits between phases to balance them.

## 6. Look at the single line diagram

Press **Single line diagram** for the panel drawn from its schedule.

![The single line diagram](img/panel-sld.png)

## 7. Save and issue

1. Press **Save**.
2. Open **Deliverables**, press **+ Distribution Panel**, choose the panel, and **Create**.
3. Press **Issue Rev A…**.

The exported workbook has the schedule, one row for each pole, and a second sheet, **Panel**, with the header figures as they were when issued.

## When the Load List changes

A load deleted or moved to another panel stays on the schedule, marked, until you remove it. A load newly supplied from the panel waits to be placed: press **Place all** or place it by hand.

Reference: [Distribution Panels](help:distribution-panels).
