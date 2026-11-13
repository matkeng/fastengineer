---
title: Cable Types
group: Project lists
order: 5
---
Cable Types is the project's catalogue of cables. The cable schedule picks each load's cable from it.

![Cable Types](img/cable-types.png)

Every project starts with a default set of 218 types: power, flex, pilot, VSD, control, instrument pairs and triples, earth, fibre and Ethernet.

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
