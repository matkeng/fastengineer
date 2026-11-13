const fs = require('fs');
const path = require('path');
const d = require('docx');
const { Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, WidthType, ShadingType,
	AlignmentType, HeadingLevel, LevelFormat, BorderStyle, PageBreak, Footer, PageNumber, VerticalAlign } = d;

const OUT = process.argv[2];
const SHOTS = path.join(path.dirname(OUT), 'screenshots');
const NAVY = '16324F', BLUE = '1A6FE0', GREY = '5B6770', LIGHT = 'EEF4FC', RULE = 'C9D6E6';
const FONT = 'Arial';
const W = 9026; // A4 content width, 1" margins

const run = (text, o = {}) => new TextRun({ text, font: FONT, ...o });
// "**bold** rest" → runs
const rich = (s, o = {}) => s.split(/(\*\*[^*]+\*\*)/).filter(Boolean).map((t) =>
	t.startsWith('**') ? run(t.slice(2, -2), { ...o, bold: true }) : run(t, o));
const P = (s, o = {}) => new Paragraph({ spacing: { after: 140, line: 300 }, ...o.p, children: rich(s, o.r) });
const H1 = (s) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [run(s)] });
const H1nb = (s) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [run(s)] });
const H2 = (s) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [run(s)] });
const B = (s) => new Paragraph({ numbering: { reference: 'bul', level: 0 }, spacing: { after: 70, line: 290 }, children: rich(s) });
const lead = (s) => new Paragraph({ spacing: { after: 200, line: 320 }, children: rich(s, { size: 24, color: NAVY }) });
const why = (s) => new Paragraph({
	spacing: { before: 120, after: 200, line: 300 }, indent: { left: 200 },
	border: { left: { style: BorderStyle.SINGLE, size: 18, color: BLUE, space: 10 } },
	children: [run('Why it matters  ', { bold: true, color: BLUE }), ...rich(s)],
});
const img = (name, caption, wpx = 600) => {
	const buf = fs.readFileSync(path.join(SHOTS, name + '.png'));
	const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
	return [
		new Paragraph({
			alignment: AlignmentType.CENTER, spacing: { before: 160, after: 60 }, keepNext: true,
			children: [new ImageRun({ type: 'png', data: buf, transformation: { width: wpx, height: Math.round(wpx * h / w) },
				outline: { type: 'solidFill', solidFillType: 'rgb', value: RULE, width: 9525 },
				altText: { title: caption, description: caption, name } })],
		}),
		new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 220 }, children: [run(caption, { italics: true, size: 17, color: GREY })] }),
	];
};
function bd(color, size = 4) { return { style: BorderStyle.SINGLE, size, color }; }
const cellB = { top: bd(RULE), bottom: bd(RULE), left: bd(RULE), right: bd(RULE) };
const cell = (children, w, fill) => new TableCell({
	width: { size: w, type: WidthType.DXA }, borders: cellB, verticalAlign: VerticalAlign.TOP,
	shading: fill ? { type: ShadingType.CLEAR, fill, color: 'auto' } : undefined,
	margins: { top: 55, bottom: 55, left: 130, right: 130 }, children,
});
const table = (widths, rows, head) => new Table({
	width: { size: W, type: WidthType.DXA }, columnWidths: widths,
	rows: [
		...(head ? [new TableRow({ tableHeader: true, children: head.map((h, i) => cell([new Paragraph({ children: [run(h, { bold: true, color: 'FFFFFF', size: 19 })] })], widths[i], NAVY)) })] : []),
		...rows.map((r) => new TableRow({ cantSplit: true, children: r.map((c, i) => cell([new Paragraph({ spacing: { line: 270 }, children: rich(c, { size: 19 }) })], widths[i], i === 0 ? LIGHT : undefined)) })),
	],
});

// ---- flow graphic: five boxes with arrows between
const flowSteps = [
	['1  Bring it in', 'MEL, equipment and instrument lists from Excel or CSV. Tags read straight off P&ID drawings.'],
	['2  One Load List', 'Every load in one live list, allocated to its plant area, load type and supply.'],
	['3  Templates', 'Load Types and Equipment Types hold the standard rows each load or instrument needs.'],
	['4  Master lists', 'Cable Schedule, Equipment, Instrument and I/O lists, always up to date.'],
	['5  Issue', 'Deliverables frozen as Rev A, B, C with the changes between them.'],
];
const bw = 1590, aw = 269; // 5*1590 + 4*269 = 9026
const none = { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' };
const flow = new Table({
	width: { size: W, type: WidthType.DXA },
	columnWidths: flowSteps.flatMap((_, i) => (i ? [aw, bw] : [bw])),
	rows: [new TableRow({
		children: flowSteps.flatMap(([t, s], i) => {
			const box = new TableCell({
				width: { size: bw, type: WidthType.DXA }, shading: { type: ShadingType.CLEAR, fill: LIGHT, color: 'auto' },
				borders: { top: bd(BLUE, 12), bottom: bd(RULE), left: bd(RULE), right: bd(RULE) },
				margins: { top: 110, bottom: 110, left: 100, right: 100 },
				children: [
					new Paragraph({ spacing: { after: 80 }, children: [run(t, { bold: true, size: 19, color: NAVY })] }),
					new Paragraph({ spacing: { line: 250 }, children: [run(s, { size: 16, color: '333333' })] }),
				],
			});
			const arrow = new TableCell({
				width: { size: aw, type: WidthType.DXA }, verticalAlign: VerticalAlign.CENTER,
				borders: { top: none, bottom: none, left: none, right: none }, margins: { left: 0, right: 0 },
				children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [run('→', { size: 24, color: BLUE, bold: true })] })],
			});
			return i ? [arrow, box] : [box];
		}),
	})],
});

// ---------------------------------------------------------------- content
const c = [];

// Cover
c.push(
	new Paragraph({ spacing: { before: 1300, after: 0 }, children: [run('ECG SOURCE LIST', { bold: true, size: 22, color: BLUE, characterSpacing: 60 })] }),
	new Paragraph({ spacing: { before: 200, after: 200, line: 620 }, children: [run('One source of truth for a project’s electrical and instrument lists', { bold: true, size: 56, color: NAVY })] }),
	new Paragraph({ spacing: { after: 420, line: 340 }, children: [run('From the mechanical equipment list and the P&IDs to issued cable schedules, load lists, instrument lists, PLC I/O lists and panel schedules, with every change tracked.', { size: 26, color: GREY })] }),
	...img('panels', 'A distribution panel schedule, built from the Load List with per-phase loading worked out.', 600),
	new Paragraph({ spacing: { before: 300 }, children: [run('Product overview  ·  Version 0.1', { size: 18, color: GREY })] }),
);

// One-page summary
c.push(H1('At a glance'));
c.push(lead('Electrical and instrumentation teams spend a large share of every project re-typing the same data: the mechanical equipment list becomes a load list, the load list becomes a cable schedule, the P&IDs become an instrument list, and all of it is redone when the next revision arrives.'));
c.push(P('**ECG Source List** keeps that data in one place. You bring in the source documents once, set up how they should be read, and the project’s lists are worked out from them. When a source changes, the lists follow, and you can see exactly what changed.'));
c.push(H2('What your team gets'));
c.push(table([2500, 6526], [
	['Less re-typing', 'Loads, cables, equipment, instruments and I/O are generated from the Load List and your own standard templates, not entered list by list.'],
	['Revisions without rework', 'A revised MEL goes through the same saved rules as the last one. The app reports which rules no longer apply and which of your edits the new file has taken in.'],
	['Nothing missed', 'Compare any two revisions of a table and see every row added, deleted, struck out, restored or changed, cell by cell.'],
	['Tags straight from drawings', 'Symbol detection finds instruments on PDF drawings and reads their tags, so the instrument list starts from the P&IDs themselves.'],
	['Consistent deliverables', 'Every list is built from the same project data and the same templates, so tags, descriptions and cable numbers agree across documents.'],
	['A full record', 'Every change is logged with who made it, when, and the old and new values. Issued revisions are frozen and can be compared at any time.'],
]));
c.push(H2('Who it is for'));
c.push(B('**Electrical and instrumentation engineers and designers** who build and maintain load lists, cable schedules, instrument lists, I/O lists and panel schedules.'));
c.push(B('**Lead engineers and engineering managers** who need the lists to be consistent, traceable and quick to re-issue when the design moves.'));
c.push(B('**Project teams** who want everyone working on the same data, on their own network, with no cloud service involved.'));
c.push(H2('How it fits together'));
c.push(flow);
c.push(new Paragraph({ spacing: { before: 160 }, children: [run('It is a Windows desktop application. Use it on a single PC, or point a team at one shared server on your office network.', { size: 19, color: GREY })] }));

// ---- Feature tour
c.push(H1('List import'));
c.push(lead('Turn someone else’s spreadsheet into your load list or instrument list, and do it again next revision without starting over.'));
c.push(P('Upload a CSV, or pick a sheet or table from an Excel workbook, and build a **recipe** of rules for reading it. The uploaded file is never changed; the rules are applied every time the data is read.'));
c.push(...img('import-overview', 'An import’s recipe: eight kinds of rule, applied in order to the latest file.', 400));
c.push(B('**Six kinds of list**: mechanical equipment lists (MEL), electrical equipment and load lists, instrument lists, and tags and symbols from drawings.'));
c.push(B('**Tidy the source**: hide or rename columns, hide rows that are not loads, add fixed-value columns, override single cells and add rows the file is missing.'));
c.push(B('**Find Replace**: make a clean column from a messy one by replacing whole values, with a count of how many rows have each.'));
c.push(B('**Calculated columns**: If / Else if / Else rules with text and number functions. A built-in function list shows each one with a worked example.'));
c.push(B('**Mapping**: point the file’s columns at the fields of your Load List. The fields themselves can be renamed, added and reordered per project.'));
c.push(B('**Strike-through is understood**: rows and cells struck through in Excel are detected, so a struck-out row can be marked deleted automatically.'));
c.push(B('**Revised files**: upload the next revision and the same rules apply. Rules that no longer match anything are listed.'));
c.push(B('**Edits report**: a workbook of every cell you changed, row you removed and row you added, each with your reason, to hand to the file’s owner. When their next revision arrives, **Check edits** shows which they have taken in and clears them.'));
c.push(B('**Share the recipe**: save an import’s settings as a file for a colleague or another project.'));
c.push(why('The mechanical list is never quite right for electrical use. Your corrections are kept as rules with reasons, not lost in a private copy of the spreadsheet, and they survive every revision.'));

c.push(H1('Symbol detection'));
c.push(lead('Find the symbols on your PDF drawings, read their tags, and get a list you can check against the drawing.'));
c.push(...img('symbols', 'A P&ID after analysis: every instrument bubble and valve found is boxed, with the tags read listed beside it.'));
c.push(B('**Any symbol, any drawing type**: draw a box around a symbol on a drawing to make a template. A ready-made P&ID instrument library is included as a starting point.'));
c.push(B('**Tags read for you**: from the PDF’s own text, or with Windows’ built-in OCR on scanned sheets. Searchable PDFs give the best results; scanned sheets may need some tags corrected.'));
c.push(B('**Tag rules per library**: a pattern splits a tag into its parts (function, loop, suffix) and writes every tag the same way.'));
c.push(B('**Review on the drawing**: reject a false match with a click, or add a symbol the analysis missed. Corrections are remembered for every later analysis of that page.'));
c.push(B('**Fine control when you need it**: thresholds per template and per page, rotated, mirrored and resized variants, masks for parts that vary, and ignored areas such as the title block.'));
c.push(B('**Tags list**: one row per tag with counts, drawings and sheets, exported to Excel or CSV, or sent straight into a list import as the start of the instrument list.'));
c.push(B('**PID Symbols**: every detection kept with its drawing, page and X / Y position in millimetres on the sheet.'));
c.push(B('**Loops**: detections grouped by loop number, with a suggested instrument type for each loop and a Verified tick that records who checked it.'));
c.push(why('The instrument list starts from what is actually on the P&IDs, and every tag can be traced back to a place on a sheet.'));

c.push(H1('Compare tables'));
c.push(lead('Two revisions of a schedule, and a clear answer to “what changed?”'));
c.push(...img('compare', 'Rev C against Rev D of a cable schedule: changed cells show old → new, and struck-out, restored, added and deleted rows are marked.'));
c.push(B('**Works on ordinary Excel files**: pick the workbook, the sheet or table, the header row and the key column. Stacked headers and merged cells are handled.'));
c.push(B('**Matched by key and by heading**, so re-sorted rows and re-ordered columns don’t show as changes.'));
c.push(B('**Six row statuses**: added, deleted, struck out, restored, changed and unchanged. Added and removed columns are labelled too.'));
c.push(B('**Sensible comparison**: 2.50 equals 2.5, and case and extra spaces can be ignored. Duplicate keys are flagged.'));
c.push(B('**Formatted Excel report**: a colour-coded Differences sheet, a Cell changes sheet with one row per change, and a Summary.'));
c.push(why('Checking a vendor’s or another discipline’s revised schedule by eye is slow and easy to get wrong. This takes minutes and leaves a report you can file.'));

c.push(H1('Project lists'));
c.push(lead('The reference lists every project needs, each with the right columns and rules already in place.'));
c.push(...img('areas', 'Plant Areas as a tree: WBS, areas, buildings, rooms and panels, rearranged by drag and drop.'));
c.push(table([2700, 6326], [
	['Plant Areas', 'The plant’s breakdown as a tree, with tag numbers, descriptions and WBS numbers.'],
	['Equipment Packages and Equipment Types', 'Vendor and supply packages, and the types of equipment in each, with their standard rows.'],
	['Load Types', 'DOL, VSD, feeder, heater and so on, by rating range, each with its standard drawing, starter chart and an attached PDF.'],
	['Equipment and Instrument Codes', 'Your coding standards, by discipline.'],
	['Electrical Equipment List', 'Switchboards, MCCs and other equipment entered directly, alongside the imported loads.'],
	['PLC List', 'Systems, racks, cards and I/O points, with card and rack types.'],
	['Instrument Types and Instrument Runsheet', 'The types of instrument loop, and the list of instrument assemblies to generate.'],
	['Drawing List and Document List', 'Registers with revision, status, issue date, equipment references and a link to each file.'],
	['Enums', 'The choice lists the others use: disciplines, drawing and document types, statuses.'],
], ['List', 'What it holds']));
c.push(P('', {}));
c.push(B('**Excel in and out on every list.** An import shows what it will add and remove before anything changes, and a file that breaks a rule is refused whole.'));
c.push(B('**Rules that protect the data**: tags and codes must be unique, required values must be filled in, and anything in use elsewhere can’t be deleted by mistake.'));
c.push(B('**Paste from Excel** into the spreadsheet-style grids.'));
c.push(...img('plc', 'The PLC List: a rack with its cards, and counts of each kind of I/O.'));

c.push(H1('The Project Load List'));
c.push(lead('Every load on the project in one live list, whatever file it came from.'));
c.push(...img('loadlist', 'The Project Master Load List: imported loads and directly entered equipment together, each with its plant area, load type and supply.', 470));
c.push(B('**Always current**: built from the latest file of every equipment-list import, through its saved rules, plus the Electrical Equipment List.'));
c.push(B('**Allocated automatically**: a load’s plant area and load type are filled in from the import where they match, and a load type is chosen by its code, units and rating range. Once a person chooses a value, it is never changed automatically.'));
c.push(B('**Supply hierarchy**: mark distribution panels and say what each load is supplied from. Loops are refused.'));
c.push(B('**Rows are remembered**: a load removed from the source stays in the list marked Deleted, with its allocations, and gets them back if it returns.'));
c.push(B('**Your own fields**: rename, add and reorder the Load List’s fields per project.'));
c.push(B('**Calculated fields**: formulas per row for active, reactive and apparent power, rated current, annual consumption and the like, with checks that flag an answer outside its expected range.'));
c.push(B('**Cable details per load**: multicore or single core, parallel cables, core size, insulation, earth size and length.'));
c.push(B('**Bulk edits**: set the plant area, load type, supply, cable details or load factors for every row the filters show.'));
c.push(H2('Load List Summary Page'));
c.push(P('Define your own totals tables over the Load List: for example the loading of each transformer including everything fed through the MCCs below it, or connected and demand kW by area. Columns can be sums, counts, minimums, maximums, averages or formulas, and each table exports to Excel.'));
c.push(why('The load list stops being a spreadsheet one person maintains. It is the shared starting point for everything downstream, and it stays in step with the mechanical list.'));

c.push(H1('Built-in engineering data'));
c.push(lead('Catalogue data is already in the project, and each load is matched to it automatically.'));
c.push(...img('motors', 'Motor Data: the WEG W22 range with its performance figures, filtered and edited like any other list.', 270));
c.push(table([2700, 2100, 4226], [
	['Motor Data', '145 motors', 'WEG W22 High Efficiency E3, 415 V 50 Hz, 2 to 8 pole: frame, speed, full load current, efficiency and power factor at 50 / 75 / 100 % load, torques and weight.'],
	['Drive Data', '297 drives', 'Rockwell PowerFlex 755TS across five voltage classes, in Open, IP54 and Flange mount, with Normal and Heavy Duty ratings and frame sizes.'],
	['Starter Coordination', '126 selections', 'NHP Type 2 coordination charts for DOL starters at 50 kA and 65 kA: circuit breaker, contactor, overload relay and settings by motor kW.'],
	['Load Factors', '30 equipment types', 'Typical nameplate and optimised load factors and average and maximum demand factors, with a default row.'],
	['Cable Types', '218 cables', 'Power, flex, VSD, control, instrument pairs and triples, earth, fibre and Ethernet.'],
], ['List', 'Starts with', 'Contents']));
c.push(P('', {}));
c.push(B('**Matched for you**: each load gets the smallest suitable motor for its rating and poles, a drive for its voltage, enclosure and duty, a starter selection from its load type’s chart, load factors for its equipment type, and a cable from its size, insulation and cores.'));
c.push(B('**Used everywhere**: the matched values are available in template rows, calculated fields and summary tables, for example a motor’s full load current or a starter’s circuit breaker.'));
c.push(B('**Yours to change**: add your own rows, import your own data from Excel, override load factors on a single load, or reset a list to its starting data.'));
c.push(P('The starting data is transcribed from the manufacturers’ published catalogues. As with any reference data, check selections against the current catalogue before they are used for design or procurement.', { r: { size: 18, color: GREY } }));
c.push(why('Looking up the same motor, drive and starter tables for every load is repetitive work. Here it is done once, the same way, for every load on the project.'));

c.push(H1('Generators and templates'));
c.push(lead('Set up what a DOL starter or a level transmitter needs once. Every load or instrument of that type then gets its rows in every list.'));
c.push(...img('loadtype-rows', 'A load type’s Cable Schedule rows. The <<tags>> are filled in with each load’s own data.'));
c.push(B('**Two generators, nothing to run.** **Power** adds the rows of each load’s load type. **Instrument** adds the rows of each Instrument Runsheet row’s equipment type. The results are worked out whenever you open them.'));
c.push(B('**Four master lists**: the Project Master Cable Schedule, Equipment List, Instrument List and IO List, each with filters and Excel and CSV export.'));
c.push(B('**Tags in template cells**: type << to pick from the load’s tag, description, rating, plant area, supply, cable, matched motor, drive and starter, and any field of the Load List.'));
c.push(B('**Follow the links**: dot notation reaches related records, such as the load type of the panel a load is supplied from, or the parent of its plant area.'));
c.push(B('**Format as you go**: modifiers for upper and lower case, proper case that keeps words like MCC and PLC as written, rounding, zero-padding, prefixes, suffixes and defaults.'));
c.push(B('**One row per cable**: a Cable Schedule row can repeat for each parallel cable or each single-core conductor and earth, with the cable looked up in Cable Types.'));
c.push(B('**Component tables**: parts that depend on the load, such as a circuit breaker or contactor chosen by rating or current range.'));
c.push(B('**Your columns**: rename, add, remove and reorder the columns of the master lists per project.'));
c.push(B('**Templates in Excel**: export and import a type’s rows as a workbook, and clone a type to make a variant.'));
c.push(why('Your standards live in the templates. A change to a template, or one more load in the Load List, flows through to every list without anyone re-typing it.'));

c.push(H1('Distribution panel schedules'));
c.push(lead('The schedule of each distribution board, built from the loads supplied from it.'));
c.push(...img('sld', 'The same panel drawn as a single line diagram: supply, upstream breaker, isolator, busbar and a breaker for each circuit.'));
c.push(B('**Three-phase and single-phase panels** with any even number of ways, shown as the two-sided switchboard schedule.'));
c.push(B('**Circuits come from the Load List**: every load supplied from the panel is there to place, and **Place all** puts them on the first free ways.'));
c.push(B('**Everything else typed in**: spare breakers, RCDs, lighting control circuits, spare spaces and headings across the schedule.'));
c.push(B('**Loading worked out**: kVA and amps per phase, maximum amps, total kW, remaining capacity in amps and per cent, and maximum kVA rating.'));
c.push(B('**Single line diagram** drawn from the schedule at the press of a button.'));
c.push(B('**Issued like any other deliverable**, with the header figures frozen in each revision.'));
c.push(why('Panel schedules are usually separate spreadsheets that drift from the load list. Here a load moved or deleted in the Load List is flagged on its panel.'));

c.push(H1('Deliverables and revisions'));
c.push(lead('Issue what you have reviewed, and know exactly how it differs from the last issue.'));
c.push(...img('deliverable-issued', 'A cable schedule issued as Rev A. The panel shows what a new revision would contain and what has changed since.'));
c.push(B('**Six kinds of deliverable**: Cable Schedule, Instrument List, PLC I/O List, Equipment List, Load List and Distribution Panel, each with a document number and title. A project can have several of each.'));
c.push(B('**Filtered and arranged**: a deliverable can take only some rows of its master list, for example one plant area, and its own choice and order of columns.'));
c.push(B('**Issue Rev A, B, C…**: the content is frozen with the date, who issued it and a description.'));
c.push(B('**Changes between revisions**: rows added, removed and changed, with old and new values per column, viewable at any time.'));
c.push(B('**Preview before issuing**: see what the next revision would contain and what has changed since the last.'));
c.push(B('**Export** any revision to Excel or CSV, named with its document number, revision and title.'));
c.push(B('**Protected history**: issued revisions can’t be edited. The latest can be withdrawn with a reason, which is recorded.'));
c.push(why('Revision control is part of the tool, not a folder of dated spreadsheets. “What changed since Rev B?” has an immediate answer.'));

c.push(H1('Teams, projects and traceability'));
c.push(lead('Everyone on the same data, with a record of who changed what.'));
c.push(...img('changelog', 'The change log: every create, change and delete, with the user, the PC and the fields that changed.'));
c.push(B('**Single PC or shared server**: each person can work alone on their own PC, or a team can share one server on the office network and work on the same data at the same time.'));
c.push(B('**No separate login**: the app uses each person’s Windows sign-in name.'));
c.push(B('**Projects are self-contained folders**: copy, move, back up or archive a project as one folder, with its data and history.'));
c.push(B('**Members per project**: administrators create projects, choose who can open them, and can start a new project with a copy of an existing project’s standards.'));
c.push(B('**Change log**: every change with the time, user, PC and old and new values, filtered by user, record type and date. A History button on each record shows just its own changes.'));
c.push(B('**No silent overwrites**: if two people edit the same record, the second save is refused with the name of who saved first.'));
c.push(P('The shared server is designed for a trusted office network. User names identify colleagues for the change log and project membership; they are not a password-protected security control.', { r: { size: 18, color: GREY } }));

c.push(H1('Installation and licensing'));
c.push(B('**Windows desktop application** with a standard setup program, and an MSI package for silent, IT-managed installation.'));
c.push(B('**Runs on your own machines**: project data stays on the PC or on your own server. No cloud service or internet connection is needed to use it.'));
c.push(B('**Nothing else to install**: reading Excel and PDF files, symbol detection and OCR are all built in or provided by Windows.'));
c.push(B('**Sample data included**: one click fills an empty project with a small invented plant, and another runs the P&ID example, so a new user can explore every feature straight away.'));
c.push(B('**Open core**: the application is published under the GNU Affero General Public License v3.0, with commercial licences available.'));
c.push(...img('dashboard', 'The Dashboard: what is in the project at a glance, and one-click ways to get started.', 560));

c.push(new Paragraph({ spacing: { before: 300, after: 120 }, children: [run('Find out more', { bold: true, size: 28, color: NAVY })] }));
c.push(P('To arrange a demonstration or discuss licensing, contact:'));
c.push(new Paragraph({ shading: { type: ShadingType.CLEAR, fill: 'FFF4CC', color: 'auto' }, spacing: { after: 120 }, children: [run('[Add contact name, email and phone number here]', { bold: true })] }));

// Feature checklist
c.push(H1('Feature checklist'));
const F = [
	['List import', 'CSV and Excel sources; tags lists from symbol detection'],
	['', 'Saved recipe: columns, rows, text columns, overrides, custom rows, Find Replace, calculated columns, mapping'],
	['', 'Strike-through detection; revised files; rules-not-applied report'],
	['', 'Edits report and Check edits; settings export and import'],
	['Symbol detection', 'Template libraries; draw templates on a drawing; P&ID example library'],
	['', 'Tags from PDF text or Windows OCR; tag patterns and formats; text scan'],
	['', 'Review, reject and add-missed on the drawing; corrections remembered'],
	['', 'Tags list export; PID Symbols with X / Y in mm; Loops with instrument types and verification'],
	['Compare tables', 'Added, deleted, struck out, restored, changed; old → new per cell'],
	['', 'Excel report with Differences, Cell changes and Summary sheets'],
	['Project lists', 'Plant Areas, Equipment Packages and Types, Load Types, Equipment and Instrument Codes'],
	['', 'Electrical Equipment List, PLC List, Instrument Types, Instrument Runsheet'],
	['', 'Drawing List, Document List, Enums; Excel export and import on every list'],
	['Load List', 'Live from all imports; automatic and manual allocation; supply hierarchy'],
	['', 'Custom fields; calculated fields with checks; cable details; bulk edits; reset'],
	['', 'Load List Summary Page with user-defined totals tables'],
	['Engineering data', 'Motor Data (WEG W22), Drive Data (PowerFlex 755TS), Starter Coordination (NHP Type 2)'],
	['', 'Load Factors with per-load overrides; Cable Types; automatic matching to each load'],
	['Generators', 'Power and Instrument generators; four project master lists'],
	['', 'Template rows with tags, dot notation and modifiers; per-cable rows; component tables'],
	['', 'Project-specific columns; template workbooks; clone'],
	['Panel schedules', 'Three-phase and single-phase; switchboard view; single line diagram; loading figures'],
	['Deliverables', 'Six types; filters and column choice; Rev A / B / C; changes between revisions'],
	['', 'Excel and CSV export; withdraw with reason'],
	['Teams and projects', 'Single PC or shared server; self-contained project folders; members; archive'],
	['', 'Change log and per-record history; conflicting saves refused'],
	['Platform', 'Windows setup and MSI; data kept on your own machines; sample data; open-core licence'],
];
c.push(table([2300, 6726], F.map(([a, b]) => [a ? `**${a}**` : '', b]), ['Area', 'Features']));

const doc = new Document({
	creator: 'ECG Source List', title: 'ECG Source List: product overview',
	styles: {
		default: {
			document: { run: { font: FONT, size: 20, color: '222222' } },
			heading1: { run: { font: FONT, size: 38, bold: true, color: NAVY }, paragraph: { spacing: { before: 0, after: 160 }, keepNext: true } },
			heading2: { run: { font: FONT, size: 25, bold: true, color: BLUE }, paragraph: { spacing: { before: 280, after: 130 }, keepNext: true } },
		},
	},
	numbering: { config: [{ reference: 'bul', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 400, hanging: 240 } } } }] }] },
	sections: [{
		properties: { page: { margin: { top: 1300, bottom: 1300, left: 1440, right: 1440 } } },
		footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [run('ECG Source List  ·  Product overview  ·  ', { size: 16, color: GREY }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: GREY })] })] }) },
		children: c,
	}],
});
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(OUT, b); console.log('wrote', OUT, b.length); });
