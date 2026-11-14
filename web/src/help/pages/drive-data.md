---
title: Drive Data
group: Project lists
order: 7
---
Drive Data lists variable speed drives and their ratings. A load is matched to a drive, and template rows, calculated fields and summary tables can use the drive's data.

![Drive Data](img/drive-data.png)

## The starting data

Every project starts with the **Rockwell PowerFlex 755TS** drives: 297, as printed in the PowerFlex 750TS-Series Technical Data. They cover 200…240 V, 380…400 V, 480 V, 575…600 V and 660…690 V, each in **Open**, **IP54** and **Flange** mount (no Flange at 690 V), with the catalog number, the frame size, and Normal Duty and Heavy Duty output amps and power.

> The figures are transcribed from the manufacturer's publication. Check a selection against the current data before using it for design or purchasing.

Click a row, or **Add drive**, to edit. **Add missing PowerFlex 755TS** adds back the starting drives that are not in the list.

## How a load is matched to a drive

A load gets the smallest drive that covers it, among the drives of:

- its **voltage class**: 200…240 V → 240, 380…415 V → 400, 440…480 V → 480, 550…600 V → 600, 660…690 V → 690;
- its **Drive enclosure** (a Load List field: Open, IP54 or Flange; blank means Open);
- its **Drive duty** (ND or HD; blank means Normal Duty).

"Covers" means the drive's continuous amps at that duty are at least the matched motor's full load current at the load's voltage. Motor Data gives the current at the motor's own voltage (415 V for the WEG table); for a load at another voltage it is scaled, so 55.4 A at 415 V counts as 95.8 A at 240 V and 33.3 A at 690 V. A load whose voltage is in none of the drives' ranges (433 V, for example) gets no drive, and a calculated field that uses the drive shows a warning saying so. When there is no motor, a rating in Amps is used; with no current at all, the drive's power must cover the load's kW. Of two that fit equally, the smaller frame is chosen.

## Using the drive's data

| Tag | Value |
|---|---|
| `<<Drive.CatNo>>` | Catalog number |
| `<<Drive.Frame>>` | Frame size |
| `<<Drive.Amps>>`, `<<Drive.kW>>` | Output at the load's duty |
| `<<Drive.Duty>>`, `<<Drive.Enclosure>>` | The duty and enclosure used |
| `<<Drive.NDAmps>>`, `<<Drive.HDAmps>>` | Normal and Heavy Duty amps |

These work in template rows, calculated fields and the Load List Summary.
