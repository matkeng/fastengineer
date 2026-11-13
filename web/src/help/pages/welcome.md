---
title: Welcome
group: Getting started
order: 1
---
ECG Source List keeps a project's electrical and instrument lists in one place. You bring in the source documents once (the mechanical equipment list, the P&IDs), say how they should be read, and the project's lists are worked out from them. When a source changes, the lists follow, and you can see what changed.

## How the data flows

1. **Bring it in.** [List import](help:import-overview) reads an equipment list from Excel or CSV through a saved set of rules. [Symbol detection](help:symbols-libraries) finds the instruments on P&ID drawings and reads their tags.
2. **One Load List.** Every load from every import, plus the equipment you enter yourself, is in the [Load List](help:load-list). Each load is given a plant area, a load type and what it is supplied from.
3. **Templates.** A [Load Type](help:load-types) (DOL, VSD, feeder…) holds the rows a load of that type needs in each list. An [Equipment Type](help:equipment-packages) does the same for an instrument assembly.
4. **Master lists.** The [Project master lists](help:master-lists) are worked out from the Load List, the Instrument Runsheet and the templates: a Cable Schedule, Equipment List, Instrument List and IO List. They are always up to date.
5. **Issue.** A [deliverable](help:deliverables) takes rows from a master list and is issued as Rev A, B, C…, each revision frozen with the changes since the one before.

## The sections of the app

| Section | What it is for |
|---|---|
| [Dashboard](help:dashboard) | What is in the project, recent activity, and shortcuts to get started |
| [Symbol detection](help:symbols-libraries) | Find symbols on PDF drawings and read their tags |
| [List import](help:import-overview) | Turn a file into a load list or instrument list with saved rules |
| [Project lists](help:working-in-the-app) | The project's reference lists, the Load List and the master lists |
| [Generators](help:generators) | What the Power and Instrument generators add to the master lists |
| [Deliverables](help:deliverables) | The lists the project issues, and their revisions |
| [Change log](help:change-log) | Who changed what, and when |
| Help | These pages |

[Compare tables](help:compare) is opened from its card on the Dashboard.

## Where to start

- New to the app: take [a tour with the sample data](help:tour).
- Starting a real project: [import a MEL and make the Load List](help:howto-import-mel).
- Looking for a button or a rule: every screen has a page here, and the **Help** button in the title bar opens the page for the screen you are on.
