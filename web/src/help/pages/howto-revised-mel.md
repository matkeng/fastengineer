---
title: Take in a revised MEL
group: How to
order: 2
---
When the mechanical equipment list is revised, you upload the new file to the same import. The rules you built apply again, and the Load List follows.

## 1. Tell the file's owner what you changed (before the revision)

Your overrides, hidden rows and added rows are corrections to their file. Send them, so the next revision includes them.

1. Open the import in **List import**.
2. Press **Edits report .xlsx**.

The workbook lists:

- **Changed cells**: the row's key, the column, the value in the file, the value you use, your reason, and the row in the file.
- **Removed rows**: the key, the reason and the row's values.
- **Added rows**: the key, the reason and the values you entered.

This is why each override, hidden row and custom row has a **Reason** box.

## 2. Upload the revision

1. On the import's **Overview** tab, under **Upload revision**, choose the new file as before.
2. Check the key column and press the upload button.

The newest revision is the one used. Earlier ones are kept.

## 3. Check the rules

Under the recipe, the Overview either says *Every rule applies to the latest file* or lists the **rules not applied**: for example a hidden row or an override whose tag is no longer in the file. Nothing needs doing about them; they are kept in case the row comes back. Remove any you no longer want.

## 4. Check your edits against the new file

Press **Check edits…**. For each of your edits it shows whether the file has taken it in:

![Checking edits against the latest file](img/import-check-edits.png)

| Edit | Is *done* when |
|---|---|
| A changed cell | The file now has the value you use (numbers compare as numbers: 11 = 11.0). It is *gone* when its row is no longer in the file |
| A removed row | The row is no longer in the file |
| An added row | The file has the row with the same values. It is *partly done*, naming the values that differ, when it has the row with others |

The done and gone ones no longer change anything, and are ticked. Press **Clear** to take the ticked edits out of the import, then **Save**. Edits that are still needed stay, for the next report.

## 5. Look at what changed in the Load List

Open **Project lists → Load List**.

- **New rows** have their plant area and load type filled in where they match. Filter for the blanks and finish them.
- **Rows that left the file** stay in the list, marked **Deleted**, with their allocations.
- **Changed ratings** may move a load to another load type of the same code, if you had not chosen its load type yourself.

To see exactly what changed between the two files, use [Compare tables](help:howto-compare) on the old and new workbooks.

## 6. Re-issue

Open **Deliverables**. Each deliverable's panel shows what has been added, removed and changed since its last revision. Review, then [issue the next revision](help:howto-issue-revision).
