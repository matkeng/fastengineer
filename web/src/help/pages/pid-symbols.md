---
title: PID Symbols and Loops
group: Project lists
order: 15
---
PID Symbols lists the symbols found on the P&IDs by [Symbol detection](help:symbols-libraries), one row for each detection.

![PID Symbols](img/pid-symbols.png)

## Where the rows come from

The list is made from every **PSL** (PID Symbols) list import: each one's latest file, through its rules and mapping. To fill it, analyse the drawings and send the analysis to a PSL import. See [the tags list](help:symbols-tags#sending-it-to-a-list-import).

It is **read only**, with filters and **Export .xlsx**. To change a row, correct the detection on the drawing, or add a rule to the import (**Open List import**).

## The columns

Each row has its import, tag and the tag's parts (function, loop, suffix), the symbol, the drawing and page, how it was found and its score, and:

- **X** and **Y**: the centre of the symbol in **mm from the sheet's top-left corner**, y downwards;
- its width and height in mm.

Positions are measured on the drawing at 200 DPI, so they are as accurate as the PDF's page size.

## Loops

The **Loops** tab groups the detections by **loop number**, in natural order, so 99 comes before 1023.

![The Loops tab](img/pid-loops.png)

For each loop it lists its function tags (FT-1023, FV-1023), their function codes, the drawings and pages it was found on, and how many detections it has.

| Column | What to do |
|---|---|
| **Instrument type** | Choose the loop's [instrument type](help:instrument-types). Until you choose, it shows the type that shares the most function codes with the loop: *Suggested: Flow Transmitter* |
| **Verified** | Tick it when you have checked the loop. It records who ticked it and when |

Both are saved as soon as they change. They are kept by loop number, so a later analysis keeps them. Detections with no loop number are counted but not listed.
