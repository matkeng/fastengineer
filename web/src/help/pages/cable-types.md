---
title: Cable Types
group: Project lists
order: 5
---
Cable Types is the project's catalogue of cables. The cable schedule picks each load's cable from it.

![Cable Types](img/cable-types.png)

Every project starts with 644 types: the original default set of 218 (power, flex, pilot, VSD, control, instrument pairs and triples, earth, fibre and Ethernet), and every other product on the product pages of the Nexans Olex Handbook 2017 (426 more, each named by its family and product code). The Load List chooses a load's cable from the original set only, so its insulation and size choices don't change.

## Current carrying capacity

Power cables of V-90 PVC and X-90 XLPE insulation in the original set carry the copper current carrying capacity, in amps, from the handbook's "Current Ratings" tables (pages 61 to 80), for a cable unenclosed in air, spaced from a surface, touching, and enclosed in conduit in air:

| Cable type | Handbook table |
|---|---|
| 2C+E | two core, single phase (pages 67, 69) |
| 3C+E and 4C+E | three and four core, three phase (pages 78, 80) |
| 1C on AC_415V | three single core cables, three phase (page 74) |

The handbook says these tables are calculated to IEC 60287 and are simplified tables for commonly used cables. It does **not** state the ambient temperature or other conditions behind them, and refers to AS/NZS 3008.1.1 for the comprehensive tables and for derating. Use them as the manufacturer's guide figures, not as a design basis.

Not included: buried and underground-duct ratings (the handbook does not state the ground conditions), aluminium, and any size a table does not print. The handbook's other products have no rating here.

## Product code

**Product code** is the Nexans Olex code. Every handbook product has its own. A type of the original set has one only where the handbook prints exactly one code for that cable (44 types); where several are printed for the same size (flat and circular ranges, 450/750 V and 0.6/1 kV ranges) it is blank until one is chosen.

## Overall diameter and bending radii

Every cable with a product code has the **overall diameter** printed on its product page. A flat cable has its width and its height.

The **installed** bending radius (the minimum for a cable in place) and the **pulling** bending radius (the minimum during installation) come from the handbook's "Cable minimum installed bending radii" table, as a multiple of the overall diameter:

| Cable | Installed | During installation |
|---|---|---|
| PVC or XLPE, single and multicore, up to 25 mm | 4 × | 6 × |
| PVC or XLPE, single and multicore, over 25 mm | 6 × | 9 × |
| Steel wire armoured, or metal tape (the screened VSD cables) | 12 × | 18 × |
| Flexible cables (Versolex) and flexible cords | 4 × | not given |

Where a product page prints its own radius it is used as printed: the Alsecure single cores (during installation) and the flexible VSD cables (installed).

Left blank, with the reason in **Bending basis**: flat cables (the rule is on a diameter), aluminium cables (the handbook's rule is for solid aluminium conductors), and Envirolex and Alsecure multicores (no rule for their materials).

The figures can be exported and imported in the Cable Types workbook.

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
