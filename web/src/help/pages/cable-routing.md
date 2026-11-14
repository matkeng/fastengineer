---
title: Cable Routing
group: Screens
order: 30
---
Cable Routing holds a map of the plant's cable ladder routes. From it the app works out each cable's length and, for each stretch of ladder, how wide the ladder has to be and what mass of cable it carries.

The map is a diagram, not a scale drawing: where things sit on it says nothing about distance. Every length is typed in.

## What is on the map

- **Equipment** is a rectangle with a tag. It comes from the [Project Master Equipment List](help:master-lists), or is typed in for anything that list does not have (a junction box, "Primary Supply").
- A **node** is a point where ladders meet or change direction. Nodes are numbered N001 to N999 as they are drawn.
- A **segment** is the ladder run between two nodes, or between a node and a piece of equipment. Segments are numbered S-001, S-002 and so on, and each has a length in metres.

Routes may form loops. A number that has been used is not given to something else, so a tag on a drawing keeps meaning the same thing. **Renumber** numbers everything again from 1 when you want a clean set.

## Drawing the map

1. Drag equipment from the list on the left onto the map (or double-click it). **Other cable ends** lists From and To tags of the cable schedule that are in no equipment list.
2. Choose **Draw route**. Click a piece of equipment or a node to start a segment, or click empty space to start at a new node.
3. Click empty space for each corner of the run. Click a node or a piece of equipment to end there, or double-click empty space to end on a new node. Clicking an existing segment puts a node on it and ends there.
4. Type the segment's length on the right and press Enter. Enter moves on to the next segment that has no length yet.

With **Select** you can drag equipment, nodes and corners, resize a rectangle by its corner, double-click a segment to put a node on it, and press Delete to remove what is selected. Deleting a node or a piece of equipment removes the segments that end on it. Scroll to zoom; drag empty space to move the view.

A segment with no length is drawn dashed. Nothing is kept until you press **Save**; Undo and Redo step through your edits.

## How a cable is routed

Each cable of the [Project Master Cable Schedule](help:master-lists) is routed from the equipment its **From** names to the equipment its **To** names, matched on the tag. It takes the shortest way by length. Equipment is never a way through: a route only starts and ends on it.

The **Cables** tab lists every cable with its route, and why a cable is not routed:

| Status | What to do |
|---|---|
| from not placed, to not placed | Put that equipment on the map. |
| no route | Join the two pieces of equipment with segments. |
| missing lengths | A segment on its route has no length: type it in. |
| same equipment | From and To are the same tag; the cable has no route. |

To send a cable another way, select it (click its row, or a cable in a segment's list), choose **Pick on the map** beside *Goes through* and click the nodes or segments it must pass, in order. *Keeps off* names segments it must not use. A cable needs a cable number to be given a route of its own.

## Cable lengths

On the **Rules** tab, a cable's length is its route's segments added up, plus a tail at each end, plus a contingency, rounded up.

Switch on **Show these lengths in the Project Master Cable Schedule** and the **Length (m)** of every routed cable comes from the map, in the master list and in new revisions of its [deliverables](help:deliverables). Cables that are not routed keep the length typed in the [Load List](help:load-list). Revisions already issued do not change, and the Load List's own cable lengths are left as they are.

The route (N001-N004…) can be written in the schedule's **Route** column: where that is blank, always, or never.

## Ladder width and mass

Cables are split into **services** (HV, LV Power, Control, Instrumentation, Comms to start with), and each service has ladders of its own on a segment. Which service a cable is in is read from its [cable type](help:cable-types) by the rules on the Rules tab; the first rule that fits wins.

For each service on a segment:

- The cables' overall diameters are added up side by side. Three single core cables of one circuit count as a trefoil, 2.15 diameters wide.
- The service's **spacing** is added beside each cable, the sum is divided by the **layers**, and the **spare** is added.
- The ladder is the next **standard width** at or above that. If the widest is not enough, the number of ladders of that width is given.
- The cables' mass per metre is added up and compared with the service's **load limit**.

The map colours each segment: grey with no cables, green within the rules, amber where the cables fit but eat into the spare, red where a ladder is too narrow or overloaded. Select a segment to see its ladders and its cables, and to say what is **installed** there (a fixed width or load limit) instead of leaving it to the rules.

Diameter and mass come from the cable type. A cable whose type has neither is counted and named in the notes, and left out of the width or the mass, so those totals are then on the low side. Fill the figures in under [Cable Types](help:cable-types).

The **Segments and ladders** tab lists every segment, and both tables export to Excel or CSV.
