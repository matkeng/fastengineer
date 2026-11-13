---
title: Change log
group: Screens
order: 32
---
The Change log records who changed which record, when, and what changed. Newest first.

![The Change log](img/change-log.png)

## What is recorded

Every create, change and delete, with:

| Column | Meaning |
|---|---|
| **When** | The date and time |
| **User** | The Windows sign-in name of whoever made the change |
| **PC** | The computer it was made from |
| **Action** | Created, Changed or Deleted |
| **Record** | What was changed, and its kind |
| **What changed** | The fields that changed |

**Details** on a row shows the old and the new value of each changed field.

![The details of a change](img/change-log-details.png)

## Finding a change

Filter by **User**, **Record type** and a **From** / **To** date, then press **Show**. **Show older changes** loads more.

## History of one record

The **History** button on a list, an import, a symbol library, a template, a generator or a deliverable shows the changes made to that record only. A table's history includes its rows.

## Limits

- Large data is logged by its details, not its contents: an uploaded file by its name and size; an analysis by the fact that it was run or deleted, and by whom.
- A very large change (more than 200 fields in one save) lists the first 200.
- The user name is the one the computer reports. It tells colleagues apart on an office network; it is not a password-protected sign-in.
