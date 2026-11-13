---
title: PLC List
group: Project lists
order: 10
---
The PLC List holds the project's PLC hardware as a four-level tree: **systems → racks → cards → IO points**.

![The PLC List](img/plc-list.png)

The chips along the top count the systems, racks and cards, and the channels of each kind (DI, DO, AI, AO).

## The four levels

| Level | Fields | Rules |
|---|---|---|
| **PLC system** | System tag, Description, Manufacturer, Model | |
| **Rack** | Rack tag, Plant area, Type (a rack type), First slot, a name | The rack tag is unique in the project |
| **Card** | Card type, Name, Spare, Notes | One card in each slot |
| **IO point** | Tag, Description, Spare | One for each channel of the card type. A tag, when filled in, is unique in the project. The signal comes from the kind of card |

## Building a rack

1. Select a system on the left, or press **+ PLC system** and fill in its tag and description.
2. Press **+ Rack** and give the rack its tag, plant area and type.
3. To add a card, choose its type beside *Add a card to the last rack* and press **+ Card**, or click the empty **+** slot.
4. Click a card to open it: name it, and type the tag and description of each channel.
5. Press **Save**.

On a card you can also **Insert empty slot** before it, move it with ◀ ▶, **Remove (leave slot empty)** or **Remove and close gap**.

## Card types and rack types

The **Card & rack types** tab holds the types that cards and racks are picked from.

![Card and rack types](img/plc-types.png)

- A **card type** has a kind (DI, DO, AI, AO, Network…), a number of channels, a part number, a description and a **First channel** (0 or 1), which says how its channels are numbered. Changing it renumbers the points and keeps their tags.
- A **rack type** has a part number, a description and a maximum number of slots.
- The grids take rows pasted from Excel. **Save types** saves them.
- **Add missing default types** puts back the starting types that were deleted.

A card's type cannot be changed to one with fewer channels while a channel it would lose has a tag or description.

## Excel export and import

**Export .xlsx** saves sheets for PLC cards, IO points, card types and rack types. **Import .xlsx…** replaces the PLC List with a workbook, after showing what it holds.

## Related

- A plant area with racks in it cannot be deleted.
- In template rows, a runsheet row's `<<Rack>>` links to its rack here: `<<Rack.System.Tag>>`, `<<Rack.PlantArea.Tag>>`. See [Template tags](help:template-tags).
