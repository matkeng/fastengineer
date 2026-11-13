---
title: Symbol detection: libraries
group: Screens
order: 10
---
Symbol detection finds symbols on PDF drawings and reads the text tag written in or beside each one. Nothing in it is specific to P&IDs: the symbols to look for and the rules for tags are kept in **libraries**, one for each kind of drawing.

For a walk-through see [Read tags from P&ID drawings](help:howto-pid-tags).

![Symbol detection](img/symbols-start.png)

## The sidebar

| Part | What it holds |
|---|---|
| **Library** | The library you are working in. **Settings** opens its settings; **New library…** makes an empty one; **Import…** reads one from a file |
| **Templates** | The symbols of the library, in the order they are matched. See [Templates](help:symbols-templates) |
| **Drawings** | The PDFs added to the library. Tick the ones to analyse |
| **Analyses** | Each analysis run, newest first, with the number of tags it found |

## The P&ID example

The app comes with a ready-made library, **P&ID instruments (ISA)**, with templates for an instrument bubble, a control valve and a valve, and tag rules for tags such as FT-1023 and TT-1026A. It is added the first time the app starts. **Add the P&ID example** puts it back if it was deleted.

Use it as it is, or copy it (**Settings → Copy…**) as the start of your own.

## Adding drawings

Press **Add PDFs…** and choose one or more PDF files. They go into the library that is selected. Each page is prepared once: it is drawn at 200 DPI with its rotation applied, and its text is read from the PDF.

The links under the button add the sample drawings: a normal PDF, and a scanned copy of it with no text.

A drawing is removed with the ✕ on its row. Its analyses are not affected.

## Library settings

![A library's settings](img/symbols-settings.png)

### Tags

- **Tag pattern** says what a tag looks like, as a regular expression. Each named group becomes a column of the tags list. The P&ID example has `function`, `loop` and `suffix`.
- **Tag format** writes every tag the same way, for example `{function}-{loop}{suffix}`.
- **Use the ISA instrument tag rules** fills in both for instrument tags.
- **Try it** shows what the pattern and format make of some example text.
- Leave the pattern blank to take the text at each template's tag points exactly as written.

**Also find tags anywhere in the page text** (the text scan) looks for the pattern in all the text of a page, not only at matched symbols. With **including two words stacked one above the other** it also joins a function code above a number, as in a bubble. It is off in a new library.

### Matching

**Threshold for new templates** is the score a match must reach, for templates made from now on. Each template has its own threshold, and any page can override it.

### Scanned drawings

**Use OCR on a page when its PDF text layer has fewer than … words** decides when a page counts as scanned. The line below says whether OCR is available on this computer. See [Troubleshooting](help:troubleshooting#scanned-drawings-and-ocr).

### Ignored text

- **Words to ignore**: text that looks like a tag but is not one, such as NOTE, SHT or REV.
- **Ignored areas**: parts of the sheet to leave out, such as the title block. Draw them on a page with **Ignore area**. They are kept as a share of the sheet, so one box fits every sheet with the same layout.

### Export, copy and delete

**Export…** saves the library as a file that **Import…** reads on another PC or project. **Copy…** makes a second library from this one. **Delete library** is available only when no drawings use the library.
