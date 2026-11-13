---
title: Motor Data
group: Project lists
order: 6
---
Motor Data lists motors and their performance figures. Each load is matched to a motor, and template rows, calculated fields and summary tables can use the motor's data.

![Motor Data](img/motor-data.png)

## The starting data

Every project starts with the **WEG W22 High Efficiency E3** range at 415 V 50 Hz, with 2, 4, 6 and 8 poles: 145 motors, as printed in the WEG W22 catalogue. For each: part number, poles, design (Standard or High-Output), kW, IEC frame, rated speed, full load current, locked rotor current, torques, efficiency and power factor at 50, 75 and 100 % load, sound pressure, moment of inertia, locked rotor times and weight.

> The figures are transcribed from the manufacturer's catalogue. Check a selection against the current catalogue before using it for design or purchasing.

## Editing

![A motor](img/motor-form.png)

- Click a row, or **Add motor**, to open the form. The grid filters by poles, design and so on.
- **Add missing WEG W22** adds back the catalogue motors that are not in the list.
- **Export .xlsx** and **Import .xlsx…** as for other lists. Use the import to load another manufacturer's range.

## How a load is matched to a motor

A load gets **the smallest motor with its number of poles whose kW is at least the load's**:

- The poles come from the Load List's **Poles** field, a number an import can map.
- A rating in HP is converted to kW. A rating in Amps matches nothing.
- Of two motors with the same kW, a Standard design is chosen before a High-Output one.

## Using the motor's data

The grey text beside each box in the form is the tag for that value.

| Tag | Value |
|---|---|
| `<<Motor.PartNo>>` | Part number |
| `<<Motor.Frame>>` | IEC frame |
| `<<Motor.FLC>>` | Full load current |
| `<<Motor.Eff100>>`, `<<Motor.PF100>>` | Efficiency and power factor at full load |

Use `|default:` for a load with no motor, for example `<<Motor.Frame|default:TBA>>`. In a calculated field the same names work: input kW is `<<rating>> / <<Motor.Eff100>> * 100`.
