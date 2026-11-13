---
title: Plant Areas
group: Project lists
order: 1
---
Plant Areas is the breakdown of the plant, as a tree: the work breakdown, areas, buildings, rooms and panels. Loads, PLC racks and instruments are placed in a plant area.

![Plant Areas](img/plant-areas.png)

## An item

| Field | Rule |
|---|---|
| **Tag number** | Required. Unique in the whole list |
| **Description** | Required. Unique in the whole list |
| **WBS number** | Optional, but not used twice |
| **Area type** | WBS, Area, Building, Room or Panel |

Uniqueness ignores capitals and extra spaces. Any type can sit under any other. A new item starts as the type below its parent's.

## Editing the tree

| To | Do this |
|---|---|
| Add an item at the top level | **Add top-level item** |
| Add an item inside another | **+▸** on the parent's row |
| Add an item after another | **+** on its row |
| Move an item | Drag its handle ⠿: drop on the top or bottom edge of a row to place it before or after, on the middle to put it inside |
| Indent, outdent, move up or down | ⇥ ⇤ ↑ ↓ on the row, or <kbd>Alt</kbd>+arrow keys |
| Delete an item | ✕ |
| Open or close a branch | ▸ / ▾, or **Expand all** / **Collapse all** |
| Find an item | Type in the filter box: tag, description, WBS or type |

Changes are a draft until you press **Save**. **Discard** drops them. The draft is kept if you look at another list and come back.

## What cannot be deleted

A plant area that is in use: one a person allocated to a load, one that holds PLC racks, or one used by the Electrical Equipment List or the Instrument Runsheet. Change those first.

## How loads get their plant area

In the [Load List](help:load-list), a load's plant area is filled in automatically when the area text from its import equals exactly one plant area's **tag number**. So use the same area numbers here as the mechanical equipment list does.
