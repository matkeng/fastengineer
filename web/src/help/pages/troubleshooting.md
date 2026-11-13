---
title: Troubleshooting and known limits
group: Reference
order: 2
---
## Starting the app

**"Waiting for the Python engine to start…"** The first start after installing or updating can take up to a minute, while the engine unpacks and Windows checks it. Later starts are quicker.

**"Engine error".** Press **Retry**. If it keeps failing, close the app, check in Task Manager that no `workbench-engine.exe` is left running, and start it again. The **Engine** section shows the engine's details, and where the project's data is kept.

**"No project".** You have not been added to a project yet. Ask an administrator to add you, then start the app again.

## Saving

**"Changed by someone else".** Someone saved the same record while you had it open. Your change was not saved and nothing was overwritten. Open the record again to get their version, then make your change again. The Change log shows what they changed.

**A save is refused.** The message says which rule was broken: a duplicate tag or code, a missing required value, a range that overlaps another, or something still in use elsewhere. Fix that value and save again.

**Something cannot be deleted.** It is in use. The message says where: a plant area allocated to loads, a load type allocated to loads, a package with equipment types, an enum item used by drawings, a deliverable with revisions.

## Reading Excel files

**Cells that should have values are blank.** The app reads the results Excel saved, not the formulas. A file written by a program and never opened in Excel has no saved results. Open it in Excel, save it, and upload it again.

**`.xls` or `.xlsb` is not accepted.** Save the file as `.xlsx`.

**The Strike through column is blank.** Only Excel files carry strikethrough. A CSV upload cannot. Strikethrough applied by conditional formatting is not detected either.

## The Load List

**A load has no load type.** Its load type text matches no load type's code, or its rating is blank or outside every range of that code. The warning names it. Add or widen a load type, fix the mapping, or choose the load type by hand.

**A load has no plant area.** Its area text does not equal a plant area's tag number. Use the same area numbers in Plant Areas as the equipment list, or choose it by hand.

**A value will not change when the import changes.** A person chose it, and a person's choice is never changed automatically. **Reset…** clears chosen values so that the import's are used again.

**A calculated cell shows ⛔.** Hover over it for the reason: usually a blank or text where a number is needed, or a division by zero. Use **Applies when** to leave out the rows the formula is not meant for, or `(<<field>> or 0)` to count a blank as 0.

## Master lists and deliverables

**A tag appears as typed, such as `<<Tga>>`.** The name matches nothing. The warning above the master list says which tag, on which type. See [Template tags](help:template-tags).

**Cable cells are blank.** The load's cable details are missing, or no row of Cable Types has that type, cores, size and insulation. The warning names the loads.

**"Issue" is refused.** A load in the deliverable has no load type. The message names the loads.

## Scanned drawings and OCR

- OCR uses the one built into Windows. It needs a display language that supports OCR (Windows Settings → Time & language). A library's **Settings** says whether OCR is available.
- Searchable PDFs, with their own text, give the best results: every tag is read.
- On scanned sheets, OCR reads loop numbers, longer codes and one-word tags (`1023`, `LIC-1030`, `PSV-1040`) but often misses two-letter function codes inside bubbles (`FT`, `PT`), so those tags come out as the number only. Correct them on the drawing with **Set tag**, or with overrides in the list import.

## Symbol detection

**Symbols are missed.** Lower the template's threshold a little and use **Test on page**. Check that the template was cut from a clean example, and that its rotated and size variants are on if the symbol appears turned or at another size.

**Too many false matches.** Raise the threshold, or put a more specific template earlier in the order.

**Title-block text is read as tags.** Draw an **Ignore area** over the title block, or add the words to **Words to ignore** in the library's settings.

**An analysis is waiting.** On a shared server analyses run one at a time, so yours queues behind others.

## Other limits

- Very large Excel sheets are slow: the whole sheet is read into memory.
- On a shared server, the user name is the one each computer reports. It identifies colleagues for the change log and project membership; it is not a password-protected sign-in.
- Exports are saved on the PC of the person exporting.
