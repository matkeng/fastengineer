---
title: Cable Types
group: Project lists
order: 5
---
Cable Types is the project's catalogue of cables. The cable schedule picks each load's cable from it.

![Cable Types](img/cable-types.png)

Every project starts with 656 types: the original default set of 218 (power, flex, pilot, VSD, control, instrument pairs and triples, earth, fibre and Ethernet), and every product in the Nexans Olex Handbook 2017 product pages (438 more, each named by its family and product code). The Load List chooses a load's cable from the original set only, so its insulation and size choices don't change.

## Current carrying capacity

Power cables of V-90 PVC and X90 XLPE insulation carry their figures from the **Nexans Olex Handbook 2017**, "Current Ratings" (IEC 60287): the copper current carrying capacity in amps, for a cable unenclosed in air, spaced from a surface, touching another, and enclosed in conduit in air. Each type shows its **conductor (mm²)** and **ampacity** and the page it came from, for 2 core, 3 and 4 core and single core cables. The basis is air at 40 °C, a conductor at 80 °C (XLPE) or 75 °C (PVC), direct sunlight and 1.0 m/s wind. Other conditions need derating under AS/NZS 3008.1, which the handbook does not reproduce.

**Product code** is the Nexans Olex product code, filled in only where the handbook prints exactly one code for that cable (its core count, insulation, conductor size and construction). Where several are printed for the same size (the flat and circular V-90 ranges, or two constructions), the field is left blank until one is chosen.

Not included: buried and underground-duct ratings (the handbook does not state the ground conditions behind them), aluminium conductors, flexible TPE cables, earth, VSD, pilot, control, instrument and network cables, and any size the handbook does not print, which stays blank. The figures can be exported and imported in the Cable Types workbook.

## A cable type

![A cable type](img/cable-type-form.png)

| Field | Example | Notes |
|---|---|---|
| **Code** | AC_240V - Power - 2C+E - 1.5 | Required. Unique. The form can make it from the other fields |
| **Sort** | 1 | The list's order |
| **Application** | AC_415V | |
| **Type** | Power | Matched against a template row's Cable Type |
| **Cores** | 3C+E | Matched against a template row's Cores |
| **Diameter** | 1.5 | The core size, mm² |
| **Voltage** | 0.6/1kV | |
| **Insulation** | PVC | Matched against the load's cable insulation |
| **Desc** | Cu PVC PVC V90 (Power) | |

Click a row, or **Add cable type**, to open the form.

**Add missing defaults** puts back any default type that was deleted, without touching the rest.

## How a load's cable is chosen

Cable sizing is done outside the app. Each load's size, insulation and number of cables are entered in the [Load List](help:load-list#cable-details). For a cable schedule row, the cable is the Cable Types row whose:

- **type** is the row's Cable Type cell (Power, VSD, Power Flex…),
- **cores** are the row's Cores cell (`1C` for a single-core cable),
- **size** and **insulation** are the load's.

If several match, the one whose application names the load's voltage (`AC_415V`) is used. See [Produce a cable schedule](help:howto-cable-schedule).
