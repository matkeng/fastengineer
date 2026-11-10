# SharePoint integration options

Status: options for discussion. Nothing here is built, and none of it has been
tested against a real Microsoft 365 tenant.

## Summary

| # | Option | What you get | Effort | Recommendation |
|---|---|---|---|---|
| 0 | OneDrive-synced library | Import from and export to SharePoint folders | None | Use today |
| 1 | Files through Microsoft Graph | Pick and save SharePoint files inside the app | Small to moderate | Build first |
| 2 | Publish lists, one way | Project lists visible in SharePoint and Power BI | Moderate | Build second |
| 3 | Open the app from SharePoint | The app's screens inside a SharePoint page | Moderate to large | Build third, if wanted |
| 4 | Two-way list sync | Edit the lists in SharePoint too | Large | Avoid |

The app's own database stays the single source of truth in every option
except 4.

## How the app works today (what matters for SharePoint)

- A Windows desktop app with a local engine. Each project is a folder holding
  one database file (`workbench.db`) plus attached files (drawings, PDFs).
- A team can instead share one engine on a server; the desktop apps connect to
  it.
- A user is identified by the Windows login name the desktop app reports. The
  server does not verify it.
- Files come in through file pickers (MEL/EEL CSV and Excel, drawings, PDFs,
  workbooks) and go out through Save As (Excel, CSV).

## Option 0: a OneDrive-synced library (no code)

Sync the SharePoint document library to each PC with OneDrive. The app's file
pickers and Save As dialogs then see it as an ordinary folder.

- Good for: importing MEL/EEL files and drawings kept in SharePoint, and saving
  exports where SharePoint versions them.
- Limits: no browsing of SharePoint from inside the app, no link back to the
  source file, and each user needs the library synced.
- Warning: never put the project folder or `workbench.db` in a synced folder.
  Sync tools copy the file while it is being written, which corrupts it. Keep
  projects on a local disk or on the shared server.

## Option 1: files in and out through Microsoft Graph

The app signs in to Microsoft 365 and talks to SharePoint directly.

- Import: a "From SharePoint" choice beside each file picker (list imports,
  drawings, Load Type PDFs, PLC List workbook) to browse sites and libraries.
- Export: "Save to SharePoint" beside Save As for the Load List, PLC List and
  generator outputs. SharePoint keeps the version history.
- The app can remember where a file came from, so "check for a newer revision"
  becomes possible for MEL files.
- Needs: Microsoft sign-in in the app (see Prerequisites), and the engine able
  to reach `graph.microsoft.com`.
- Stays the same: everything works offline from local files as it does now.

## Option 2: publish the project lists to SharePoint Lists (one way)

A "Publish to SharePoint" action copies the project lists into SharePoint
Lists on a site you choose: Plant Areas, Equipment Packages and Types, Load
Types, Equipment and Instrument Codes, the Electrical Equipment List, the Load
List and the PLC List.

- People without the app can view, filter and export them, and Power BI can
  report on them.
- Editing stays in the app. The published lists are overwritten on the next
  publish, so changes made in SharePoint are lost; the lists should be set
  read-only for everyone but the publishing account.
- Trees (Plant Areas, PLC List) are flattened to rows with a parent column and
  a level column. References become text (for example the plant area's tag).
- Limits to design around: SharePoint list views slow down past 5,000 items,
  and Graph throttles large writes, so publishing sends only changed rows in
  batches.
- Open choice: publish on demand (a button), or automatically after each save.

## Option 3: open the app from SharePoint

The app's screens already run in a web browser against the shared server, so a
SharePoint page could show them, embedded or as a link.

- Needs real sign-in first. Today the server trusts the name the desktop app
  sends; a browser user could claim any name. The server would have to verify
  a Microsoft sign-in on every request and take the user's identity from it.
- Needs HTTPS on the shared server, and the server reachable from wherever
  people open SharePoint.
- Some features are desktop-only today (Save As to a chosen local path, the
  Windows OCR used by symbol detection on a local engine) and would behave as
  they do in shared-server mode.
- Benefit beyond SharePoint: verified sign-in closes the "user name is
  reported, not verified" gap for the shared server generally, and project
  administrators could be named by Microsoft account.

## Option 4: two-way sync with SharePoint Lists (not recommended)

Letting people edit the lists in SharePoint and syncing changes back.

- The app enforces rules SharePoint cannot: tags unique across the EEL and
  every import, no supply loops, panels that can't be removed while rows are
  supplied from them, "can't delete while in use".
- Edits made in SharePoint would bypass those rules. Rejecting them afterwards
  means conflict screens and partial syncs.
- If people need to edit without the desktop app, Option 3 gives them the real
  app with the rules intact.

## Prerequisites for options 1 to 3

- SharePoint Online (Microsoft 365). SharePoint Server on-premises does not
  use Microsoft Graph and would need a different approach.
- An application registered in your Microsoft Entra ID tenant, usually with
  admin consent. Access can be limited to chosen sites (`Sites.Selected`)
  rather than every site.
- The tenant ID and client ID entered as app settings. Everything
  SharePoint-related stays hidden until they are set.
- Sign-in tokens stored in the Windows credential store, not in the project
  database.

## Suggested order

1. Use Option 0 now if SharePoint files are the immediate need.
2. Build sign-in and Option 1. This proves the app registration and
   permissions against your tenant with the least at stake.
3. Build Option 2 on the same sign-in.
4. Decide on Option 3 once 1 and 2 are in use; it is the largest change and
   the only one that alters how the shared server is secured.

## Questions that decide the design

- Is it SharePoint Online, and can you or IT register the application?
- Which site and libraries hold the MEL/EEL files and receive the exports?
- Should publishing the lists be a button or automatic?
- For Option 3: should anyone in the tenant be able to open the app (seeing
  only their projects), or only a named group?
