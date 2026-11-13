---
title: Equipment Codes and Instrument Codes
group: Project lists
order: 4
---
Two lists of codes: the kinds of equipment and the kinds of instrument the project uses.

![Equipment Codes](img/equipment-codes.png)

Click a row, or **Add equipment code** / **Add instrument code**, to open the form. **Save** saves straight away; **Save and add another** saves and opens an empty form.

![An equipment code](img/equipment-code-form.png)

## Equipment Codes

| Field | Rule |
|---|---|
| **Code** | Required. Unique, ignoring capitals and extra spaces |
| **Name** | Required. Unique |
| **Description** | Optional |
| **Disciplines** | Any number of the project's disciplines (Electrical, Instrumentation, Mechanical…). The grid can be filtered by one |

The disciplines offered come from the [Enums](help:enums). An equipment code is the **Equipment type** of an item in the [Electrical Equipment List](help:eel); one in use cannot be deleted.

## Instrument Codes

![Instrument Codes](img/instrument-codes.png)

| Field | Rule |
|---|---|
| **Code** | Required. Unique |
| **Name** | Required. Unique |
| **Description** | Optional |
| **PLC code** | Optional text. Several codes may share one |
