---
title: A tour with the sample data
group: Getting started
order: 2
---
The app can fill an empty project with a small invented plant, so you can see every part working before entering your own data. It takes about ten minutes.

> Loading the sample data only fills lists that are still empty. It is safe on a project in use, but for a first look an empty project is clearer.

## 1. Load the sample data

1. Open the **Dashboard**.
2. Under **Start**, press **Load sample data**.
3. Press **Try the P&ID example**. This adds a sample drawing to Symbol detection, with a ready-made library of instrument symbols.

![The Dashboard after loading the sample data](img/dashboard.png)

The cards along the top now count what the project holds: plant areas, packages, load types, a MEL import of nine loads, a PLC, and one deliverable of each type.

## 2. See where the loads come from

1. Open **List import** and click **Sample plant MEL**.
2. The **Overview** tab shows the file and the rules that read it. The **Mapping** tab shows which column of the file fills which field of the Load List.
3. Open the **Result** tab to see the table after the rules.

More: [List import](help:import-overview).

## 3. Look at the Load List

1. Open **Project lists** and, under **Project master lists**, click **Load List**.
2. Each row is a load. Its **Plant area** and **Load type** were filled in from the import (shown in italics) and can be changed here.

![The Project Master Load List](img/load-list.png)

More: [Load List](help:load-list).

## 4. See what a load type adds

1. In **Project lists**, click **Load Types**, then the **DOL** row.
2. Open the **Cable Schedule** tab. These rows are added to the cable schedule for every DOL load, with the `<<tags>>` replaced by that load's data.
3. Under **Project master lists**, open **Cable Schedule** to see the result for every load.

More: [Load Types](help:load-types) and [Template tags](help:template-tags).

## 5. Analyse the sample drawing

1. Open **Symbol detection**.
2. Tick **pid-sample.pdf** under **Drawings** and press **Analyse 1 drawing(s)**.
3. When it finishes, the drawing opens with every symbol it found in a box.

![A drawing after analysis](img/symbols-review.png)

More: [Analysing and reviewing drawings](help:symbols-analyse).

## 6. Issue a revision

1. Open **Deliverables** and click **Sample cable schedule**.
2. Press **Issue Rev A…**, type a description and confirm.

The rows are now frozen as Rev A. Change something in the Load List and come back: the panel shows what Rev B would add, remove and change.

More: [Deliverables](help:deliverables).

## 7. Compare two files

On the **Dashboard**, press **Compare tables**, then **Use sample Rev C (old)** and, for the new table, **Use sample Rev D (new)**. More: [Compare tables](help:compare).
