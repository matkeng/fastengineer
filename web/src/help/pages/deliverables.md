---
title: Deliverables
group: Screens
order: 31
---
A deliverable is a list the project issues, with a document number, a title and revisions.

For a walk-through see [Issue, compare and withdraw a revision](help:howto-issue-revision).

![Deliverables](img/deliverables.png)

## Types

| Type | Its content comes from |
|---|---|
| Cable Schedule | The Project Master Cable Schedule |
| Instrument List | The Project Master Instrument List |
| PLC I/O List | The Project Master IO List |
| Equipment List | The Project Master Equipment List |
| Load List | The [Project Master Load List](help:load-list) |
| Distribution Panel | One panel of [Distribution Panels](help:distribution-panels) |

A project can have several of each type, for example a cable schedule for each area.

## Making one

Press **New deliverable**, or the **+** button under a type in the sidebar. Choose the **Type**, type a **Name** (unique), choose what the **Content** comes from, and press **Create**.

![A new deliverable](img/deliverable-new.png)

## An open deliverable

![A deliverable](img/deliverable.png)

| Field | Meaning |
|---|---|
| **Name** | Unique among the deliverables |
| **Document number**, **Document title** | They name the exported files |
| **Content from** | The master list, the Load List or the panel |
| **Only rows where** | Optional: only the rows where one column is one of a list of values, for example *Plant Area* is 100, or *Confirmed* is TRUE |
| **Columns** | **Choose and order…** picks which columns the deliverable has and in what order. The column revisions are compared by (Tag, or Cable Number) has to stay |

![Choosing and ordering the columns](img/deliverable-columns.png)

Changes to these are saved with **Save**.

The blue panel says what the deliverable holds now and, once a revision exists, what has changed since: *Since Rev A: 2 added · 0 removed · 1 changed*.

A deliverable follows its source until a revision is issued. Under the revisions, **Current (not issued)** shows the **Rows** as they are now and the **Changes** against the latest revision.

A **Load List** deliverable can show the list's ten main columns, the load's power cable, and any of the project's Load List fields.

## Revisions

- **Issue Rev A…** (then B, C… and after Z: AA, AB…) freezes the rows and columns as they are, with the date, who issued it and the description you type.
- Each revision keeps its rows and the changes against the revision before it: added, removed and changed rows, with old → new for each column.
- **View** shows a revision. **Excel** and **CSV** export it. The file is named with the document number, the revision letter and the title.
- Issued revisions cannot be edited. Only the description can be amended (**edit**).
- **Withdraw** removes the **latest** revision, with a reason. Its frozen copy is deleted, the letter is used by the next issue, and the change log records it.

![An issued revision](img/deliverable-issued.png)

## What blocks issuing

A load with **no load type** blocks issuing a deliverable generated from the Load List. The message names the loads. Other warnings (a tag that matches nothing, a cable not found) do not block it.

## Deleting

A deliverable with revisions cannot be deleted. A panel that a deliverable issues cannot be deleted.
