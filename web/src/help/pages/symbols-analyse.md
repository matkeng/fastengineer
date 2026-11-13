---
title: Symbol detection: analysing and reviewing
group: Screens
order: 12
---
## Analysing

1. Tick the drawings to analyse under **Drawings**.
2. Press **Analyse N drawing(s)**.

The analysis runs in the background with a progress bar, and can be cancelled. On a shared server, analyses from several people run one at a time.

Tags are read from the PDF's own text. On a scanned page, with no text or very little, Windows' built-in OCR is used.

## Reviewing the drawings

When the analysis finishes it opens on the drawing, with every detection in a box. The colour of a box is its template's. Step through the pages of the analysis with ‹ and ›.

![A drawing after analysis](img/symbols-review.png)

The panel on the right lists the tags found on the page, and the templates with their thresholds.

### What is shown

The tick boxes above the panel turn layers on and off:

| Layer | Shows |
|---|---|
| **Symbols** | Symbols matched by a template |
| **Text tags** | Tags found by the text scan alone |
| **Text** | Every piece of text the app could read, in a light yellow box |
| **Ignored areas** | The library's ignored areas |
| **Rejected** | Detections you marked as false |

### Correcting the result

- **A false match.** With **Select** on, click its box and mark it as not a symbol. It turns grey and crossed out. **Restore** undoes it.
- **A symbol that was missed.** Press **Add missed**, pick its template and click on the symbol. The box snaps to the best match near the click, and the tag is read from the template's tag points. Type the tag if nothing is read.
- **A wrong tag.** Click the box and use **Set tag**.

![A detection selected for review](img/symbols-review-box.png)

Corrections are kept with the page. Every later analysis of that page applies them again, and the tags list, the exports and any list import fed from the analysis update at once.

### Page tools

| Tool | What it does |
|---|---|
| **Select** | Click boxes to review them |
| **Add missed** | Place a symbol the analysis did not find |
| **New template** | Draw a box to cut a new template from this page |
| **Ignore area** | Draw an area whose text and symbols are left out, for example the title block |
| − + **Fit** | Zoom |
| **Analyse page** | Analyse this one page again, for example after changing a threshold |

### Thresholds for one page

Under **Templates on this page**, type a threshold to use for that template on this page only, or tick **Skip** to leave the template out here. Then press **Analyse page**.

**Always OCR** makes the drawing's pages use OCR even when the PDF has text, for a PDF whose text layer is wrong.
