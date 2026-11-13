---
title: Electrical Equipment List
group: Project lists
order: 12
---
The Electrical Equipment List (EEL) is for equipment you enter yourself, in addition to anything imported: typically the switchboards, MCCs and distribution boards that the mechanical equipment list does not have.

![The Electrical Equipment List](img/eel.png)

Click a row, or **Add equipment**, to open the form.

![An item of the Electrical Equipment List](img/eel-form.png)

## An item

| Field | Rule |
|---|---|
| **Tag number** | Required. Unique across this list and every MEL and EEL import's rows |
| **Description** | Required |
| **Equipment type** | Required. An [equipment code](help:codes) |
| **Plant area** | Required |
| **Vendor package** | Optional. An [equipment package](help:equipment-packages) |
| **Load type** | Optional. Choosing one copies its kW or Amps, voltage and phases |
| **Rating**, **kW or Amps**, **Voltage**, **Phases** | Optional |
| **Distribution panel** | Tick it for a switchboard or panel that supplies other loads |
| **Supplied from** | Primary Supply, or a panel of the Load List |
| **Manufacturer**, **Model number** | Optional |
| **Supplied by**, **Installed by**, **Terminated by** | Optional. Equipment packages |

## Every item is also a load

Each item is a row of the [Load List](help:load-list), with the source "Electrical Equipment List". Its plant area, load type, panel and supply are set **here** and shown read-only there. Other loads can be supplied from its panels.

A deleted item's row stays in the Load List, marked deleted.

## Rules

- A panel cannot stop being a panel, or be deleted, while loads are supplied from it.
- Supplies cannot loop: a panel cannot be supplied, directly or through others, from itself.
- The plant areas, load types, equipment codes and packages the list uses cannot be deleted.
- If an import later gains a row with the same tag, the item is marked ⚠.
