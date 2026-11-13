---
title: Read tags from P&ID drawings
group: How to
order: 3
---
This finds the instruments on a set of P&IDs, reads their tags, and puts the result into the project.

## 1. Choose or make a library

1. Open **Symbol detection**.
2. For ISA-style P&IDs, start from **P&ID instruments (ISA)**. For your own drawing standard, open its **Settings**, press **Copy…**, and work in the copy.

## 2. Add the drawings

Press **Add PDFs…** and choose the P&IDs. Searchable PDFs, exported from CAD, read far better than scans.

## 3. Check the templates on one sheet

1. Click a drawing to open it.
2. Press **Analyse page**.
3. Look at what was found. If a kind of symbol is missed, make a template for it: press **New template**, drag a box around a clean example, and press **Create template**. Then click where each part of its tag is written.

![The template editor](img/symbols-template.png)

Put specific symbols above general ones in the sidebar. Details: [templates](help:symbols-templates).

## 4. Leave out the title block

Text in the title block and notes often looks like a tag. Press **Ignore area** and draw a box over it. The area applies to every sheet of the same layout.

## 5. Analyse everything

Tick the drawings under **Drawings** and press **Analyse N drawing(s)**.

## 6. Review

Step through the pages. For each:

- click a false match and mark it as not a symbol;
- use **Add missed** for a symbol that was not found;
- use **Set tag** where a tag was read wrongly.

![Reviewing a page](img/symbols-review.png)

Your corrections are remembered for every later analysis of the page.

## 7. Use the result

Open the analysis's **Tags list**.

- For a quick list, **Export .xlsx**.
- To keep it in the project, press **Send to a list import…**, choose **PSL → PID Symbols**, press **Send**, then open the import and **Save** it.

The detections are now in **Project lists → PID Symbols**, each with its drawing, page and position. On its **Loops** tab, give each loop an instrument type and tick **Verified** as you check it.

![The loops found on the drawings](img/pid-loops.png)

## When the drawings are revised

Add the new PDFs, analyse again, and send the new analysis to **the same import**. It becomes the next revision of the import's file. Rules in the import, and the instrument types and Verified ticks on the loops, are kept.
