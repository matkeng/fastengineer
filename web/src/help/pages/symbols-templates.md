---
title: Symbol detection: templates
group: Screens
order: 11
---
A template is a picture of one symbol, with the places where its tag is written. The analysis looks for every template on every page.

## Making a template

1. Press **Draw on a drawing…** in the sidebar, or **New template** above any page.
2. Drag a box around one clean example of the symbol.
3. Adjust the box with its handles. The preview shows what will be cut: it is trimmed to the symbol's lines, and the text inside it is shown in yellow boxes.
4. Press **Create template**.

**or add an image…** makes a template from a picture file of the symbol.

## The template editor

Click a template in the sidebar to open it.

![The template editor](img/symbols-template.png)

### Tag points

A tag point is where one part of the tag is written. For an instrument bubble there are two: the function letters above and the number below.

- Choose **Tag points**, then click on the symbol where each part is written. Drag a point to move it.
- The table lists each point and, for a template cut from a page, what it reads there.
- **Tag format** joins the parts, for example `{Function}{Number}`. Leave it blank to join them with "-". The library's own tag format is applied afterwards.
- **Show text** shows the page's text on the template. It is only for show: the template is matched with its text erased, so a bubble matches whatever tag is written in it.

### Match threshold

How good a match must be. Lower finds more symbols and more false matches. Any page can override it or skip the template.

### What is compared

| Choice | Use it when |
|---|---|
| **the symbol's lines, widened by N px** | The usual choice. Pipes or text crossing the symbol do not count against it |
| **a custom mask (paint or upload)** | Parts of the symbol vary. Paint the parts to compare with **Paint mask**, remove with **Erase mask**, or upload a mask image |
| **the whole rectangle** | The symbol is a filled shape, or the space around it matters |

### Variants

- **Also find it rotated 90°, 180°, 270°** and **mirrored**.
- **Sizes**: a list such as `0.9, 1, 1.1` also looks for the symbol a little smaller and larger. `1` is as cut.
- **Active**: untick to leave the template out of analyses without deleting it.
- **Skip if more matches than**: a template that matches more than this many times on a page is reported as a problem and not used, which usually means its threshold is too low.

### Testing

**Test on page** shows the matches and their scores on a page with the settings as they are now, before you save. **Clear test** removes them.

**Save** keeps the changes; **Discard** drops them. **Delete template** removes it.

## Order matters

Templates are matched in the order of the sidebar, and each match is blanked out before the next template runs. Put specific symbols before general ones: a control valve before a plain valve, so the valve template does not claim part of every control valve. The ▲ ▼ buttons move a template.
