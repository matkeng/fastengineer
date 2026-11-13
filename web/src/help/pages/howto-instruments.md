---
title: Generate instrument and I/O rows
group: How to
order: 7
---
The Instrument generator works like the Power one, with different inputs: an **equipment type** is the template, and each row of the **Instrument Runsheet** is one assembly to generate.

## 1. Make an equipment type with its rows

1. Open **Project lists → Equipment Packages**.
2. Add a package if you need one (**Add package**), then press **+ Type** on it and name the type, for example *Centrifugal pump*.
3. Press **Lists** on the type.
4. On each tab, add the rows one assembly of this type needs:
   - **Instrument List**: a row for each instrument, such as a pressure transmitter and a flow switch.
   - **PLC I/O List**: a row for each signal.
   - **Cable Schedule**: a row for each instrument cable.
5. Use the runsheet's tags for anything that differs from one assembly to the next.

![The rows of an equipment type](img/equipment-type-lists.png)

| Cell | Example |
|---|---|
| Instrument tag | `PT-<<#1>>` |
| Description | `<<MECH>> discharge pressure <<SUF>>` |
| Plant Area | `<<Area>>` |
| P&ID | `<<PID>>` |
| Rack | `<<Rack>>` |
| The parent's description | `<<Parent.Description>>` |

`<<#1>>`, `<<#2>>`… are the runsheet's number columns: use them for loop numbers. Dot notation follows links, so `<<Parent.PlantArea.Tag>>` is the plant area of the parent equipment.

6. Press **Done**, then **Save**.

## 2. Fill in the Instrument Runsheet

1. Open **Project lists → Instrument Runsheet**.
2. Add a row for each assembly:
   - **Equipment Type Ref**: the equipment type's name.
   - **Area Ref**: a plant area's tag number.
   - **Parent Equipment Ref**: the tag of the equipment it belongs to, from the MEL or the Electrical Equipment List.
   - **#1, #2, …**: the loop numbers and anything else the rows use.
3. Paste from Excel if you have the list there.
4. Fix any cell marked as not matching, then press **Save**.

![The Instrument Runsheet](img/instrument-runsheet.png)

## 3. Check the master lists

Open **Project master lists → Instrument List** and **IO List**. Each runsheet row has added its equipment type's rows. The **Generator** column says *Instrument*, and **Confirmed** is the runsheet row's.

![The Project Master IO List](img/master-io-list.png)

## 4. Confirm as the design firms up

Set **Confirmed** to TRUE on runsheet rows as they are agreed. In a deliverable, set **Only rows where** *Confirmed* is *TRUE* to issue only those.

## Loads can carry instruments too

If an instrument always comes with a kind of load (a local control station with every DOL starter), put its row on the **load type**'s Instrument List and PLC I/O List tabs. It is then generated for every load of that type without a runsheet row.

Reference: [Instrument Runsheet](help:instrument-runsheet), [Equipment Packages and Equipment Types](help:equipment-packages), [Template tags](help:template-tags).
