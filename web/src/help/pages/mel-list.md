---
title: MEL
group: Project lists
order: 11
---
The MEL list shows every row of the latest file of every **MEL import**, with its columns as the import's column rules leave them.

![The MEL list](img/mel-list.png)

- It is **read only**. It changes when a file is uploaded or an import's rules change, in [List import](help:import-overview). **Open List import** goes there.
- Rows that were unticked in the import's **Rows** tab are here too, marked *not a load* in the **In the Load List** column. They are not in the Load List.
- It can be exported to Excel, not imported.

## What it is for

Equipment that is not an electrical load (a chute, a bin, a conveyor frame) still matters to instruments mounted on it. The [Instrument Runsheet](help:instrument-runsheet)'s **Parent Equipment Ref** can name any tag in this list, load or not.

The [Drawing List](help:drawing-document-lists) also checks the tags in a drawing's equipment reference against it.
