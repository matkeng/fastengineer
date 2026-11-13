---
title: Symbol detection: the tags list
group: Screens
order: 13
---
Open an analysis under **Analyses** and choose **Tags list**.

![The tags list of an analysis](img/symbols-tags.png)

## What is in it

One row for each different tag:

| Column | Meaning |
|---|---|
| Tag | The tag, written in the library's tag format |
| The pattern's groups | For P&IDs: function, loop, suffix |
| Count | How many times the tag was found |
| Drawings, Sheets | Where it was found |
| Symbols | The templates that matched |
| Source | *Template* for a tag read at a matched symbol; *text scan* for one found in the page text alone |

## Exporting

- **Export .xlsx** saves the tags list, with a second sheet, *Detections*, of every single detection.
- **Export .csv** saves the tags list.

## Sending it to a list import

**Send to a list import…** passes the analysis to [List import](help:import-overview), where saved rules can tidy it and map it onto a list.

![Sending an analysis to a list import](img/symbols-send.png)

Choose a new import or an existing one, and the kind of list:

| Kind | What the import gets | It fills |
|---|---|---|
| **PSL → PID Symbols** | One row for every detection, tagged or not, with its drawing, page, symbol, score and its **X and Y centre in mm** from the sheet's top-left corner | The [PID Symbols](help:pid-symbols) list |
| **PIL → instrument list** | One row for each tag | An instrument list |

Press **Send**, then **Open it in List import** and **Save** the import.

![A PID Symbols import fed from an analysis](img/import-psl.png)

Sending a later analysis to the same import adds it as the next revision of the file, and the import's rules apply again. Rows keep the same key from one analysis to the next (drawing, page, tag or symbol, and position to the millimetre), so overrides and hidden rows stay on the right rows.

## Deleting an analysis

**Delete** removes the analysis and its results. Corrections made on the drawing pages are kept.
