// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// The screenshots, in groups. See help-screenshots.cjs.
const h = require('./help-screenshots.cjs');
const { group, shot, nav, list, click, fill, vis, esc, wait } = h;
const ENGINE = process.env.HELP_ENGINE_URL || 'http://127.0.0.1:8765';

/** Try one step; a failure is reported and the group carries on. */
const closeAll = async () => {
	for (let i = 0; i < 4 && (await h.page.locator('dialog[open]').count()); i++) {
		await h.page.locator('dialog[open] .modal-head .close').last().click({ timeout: 2000 }).catch(() => h.page.keyboard.press('Escape'));
		await wait(300);
	}
};
const tryDo = async (what, fn) => {
	try { await fn(); } catch (e) { console.log('   skip', what, '-', String(e.message).split('\n').slice(0, 12).join(' ').replace(/\u001b\[\d+m/g, '').slice(0, 900)); }
	await closeAll();
};
/** Click something inside the open dialog. */
const inDialog = async (sel, ms = 800) => { await h.page.locator('dialog[open]').locator(sel).filter({ visible: true }).first().evaluate((el) => el.click(), null, { timeout: 6000 }); await wait(ms); };
const row = (text) => `main table tbody tr:has-text("${text}")`;

group('setup', async () => {
	const page = h.page;
	await page.request.post(`${ENGINE}/api/sample-data`, { headers: { 'X-Workbench-User': 'demo' } });
	await nav('Symbol detection');
	if (!(await page.locator('text=/\\d+ tags/').count()) || !(await page.locator('.ref-nav .name:text-is("pid-sample.pdf")').count())) {
		if (!(await page.locator('.ref-nav .name:text-is("pid-sample.pdf")').count())) {
			await nav('Dashboard');
			await click('button.starter:has-text("Try the P&ID example")', 12000);
			await nav('Symbol detection');
		}
		const tick = vis('.ref-nav li:has(.name:text-is("pid-sample.pdf")) input[type=checkbox]');
		if (!(await tick.isChecked())) await tick.check();
		await wait(800);
		await click('button:has-text("Analyse 1 drawing")', 25000);
	}
});

group('dashboard', async () => {
	await click('button:has-text("Refresh")', 1200);
	await shot('dashboard');
});

group('compare', async () => {
	const page = h.page;
	await click('button.starter:has-text("Compare tables")');
	await shot('compare-start');
	const walk = async (prefix) => {
		const names = ['workbook', 'sheet', 'header', 'key'];
		for (const n of names) {
			const radio = page.locator('main input[type=radio]:visible');
			if ((await radio.count()) && !(await page.locator('main input[type=radio]:checked:visible').count())) await radio.first().check();
			await wait(500);
			if (prefix) await shot(`${prefix}-${n}`);
			const next = page.locator('main button:text-is("Next"):visible');
			if ((await next.count()) && (await next.first().isEnabled())) await click('main button:text-is("Next"):visible', 1300);
			else break;
		}
		await click('button:has-text("Use this table")', 1300);
	};
	await click('button:has-text("Use sample Rev C")', 1500);
	await walk('wizard');
	const nx = page.locator('button:has-text("Next: new table")');
	if (await nx.count()) await nx.click();
	await wait(800);
	await click('button:has-text("Use sample Rev D")', 1500);
	await walk('');
	const go = page.locator('button:has-text("Compare →")');
	if ((await go.count()) && (await go.isEnabled())) await go.click();
	await wait(2500);
	await shot('compare-result');
	await click('button:has-text("Changed columns only")', 900);
	await shot('compare-changed-columns');
});

group('symbols', async () => {
	const page = h.page;
	await nav('Symbol detection');
	await shot('symbols-start');
	await click('button:text-is("Settings")', 1200);
	await shot('symbols-settings');
	await esc();
	await nav('Symbol detection');
	await click('.ref-nav li:has-text("Instrument bubble")', 1500);
	await shot('symbols-template');
	await nav('Dashboard'); await nav('Symbol detection');
	await vis('.ref-nav li:has(.name:text-is("pid-sample.pdf")) .name').click(); // loads the drawing's pages
	await wait(2000);
	await page.locator('text=/\\d+ tags/').first().click();
	await wait(3000);
	await shot('symbols-review');
	await tryDo('box', async () => { await page.mouse.click(395, 318); await wait(700); await shot('symbols-review-box'); });
	await click('main button:has-text("Tags list")', 1200);
	await shot('symbols-tags');
	await click('button:has-text("Send to a list import")', 1000);
	await shot('symbols-send');
	await tryDo('psl', async () => {
		if (await page.locator('nav.menubar button:has-text("List import")').count()) {
			await click('main button:text-is("Send")', 2500);
			await tryDo('open', () => click('button:has-text("Open it in List import")', 1500));
			await tryDo('save', () => click('main button:text-is("Save"):enabled', 1500));
			await shot('import-psl');
		}
	});
});

group('import', async () => {
	const page = h.page;
	const tab = (t) => click(`main .subtabs button:has-text("${t}"), main button:text-is("${t}")`, 1000);
	await nav('List import');
	await shot('import-list');
	await click('text=Sample plant MEL', 1500);
	await shot('import-overview');
	await tab('Columns'); await shot('import-columns');
	await tryDo('rows', async () => {
		await tab('Rows');
		await vis(`${row('LP-601')} input[type=checkbox]`).uncheck();
		await fill('input[placeholder="Why it is hidden"]', 'Entered in the Electrical Equipment List');
		await wait(400); await shot('import-rows');
	});
	await tryDo('text', async () => {
		await tab('Text columns'); await click('button:has-text("Add text column")');
		await fill('input[aria-label="Column name"]', 'Source'); await fill('input[aria-label="Value"]', 'MEL');
		await wait(300); await shot('import-text');
	});
	await tryDo('overrides', async () => {
		await tab('Overrides');
		await vis(`${row('P-103')} td >> nth=4`).click(); await wait(600);
		await fill('input[placeholder="New value"], label:has-text("New value") input', '37').catch(() => page.locator('.modal input, dialog input').first().fill('37'));
		await fill('input[placeholder^="Why the file"]', 'Upsized per vendor data');
		await shot('import-override-dialog');
		await inDialog('button:text-is("Apply")'); await shot('import-overrides');
	});
	await tryDo('custom', async () => {
		await tab('Custom rows'); await click('button:has-text("Add row")');
		await fill('input[placeholder="Tag (key)"], label:has-text("Tag (key)") input', 'P-104').catch(() => page.locator('.modal input, dialog input').first().fill('P-104'));
		await fill('input[placeholder="Why the row is added"]', 'Missing from the MEL');
		const cells = page.locator('.modal input[placeholder="-"], dialog input[placeholder="-"]');
		await cells.nth(0).fill('100'); await cells.nth(1).fill('Spare feed pump'); await cells.nth(2).fill('DOL'); await cells.nth(3).fill('7.5'); await cells.nth(4).fill('415');
		await shot('import-custom-dialog');
		await inDialog('button:text-is("Add")'); await shot('import-custom');
	});
	await tryDo('replace', async () => {
		await tab('Find Replace'); await click('button:has-text("Add find/replace column")');
		await page.selectOption('select:near(:text("Column to read"))', { label: 'Type' }).catch(async () => { const s = page.locator('main select').last(); await s.selectOption({ label: 'Type' }); });
		await wait(600);
		await page.locator('main input[placeholder="New column name"], label:has-text("New column name") input').first().fill('Starter');
		await wait(500); await shot('import-replace');
	});
	await tryDo('calculated', async () => {
		await tab('Calculated'); await click('button:has-text("Add calculated column")');
		await fill('main label.field:has-text("Column name") input', 'Size band');
		await fill('input[placeholder^="condition"]', '<<kW>> >= 30');
		await fill('main input[aria-label="If value"], main input[placeholder="If value"]', 'Large'); await fill('main input[aria-label="Else value"], main input[placeholder="Else value"]', 'Small');
		await wait(600); await shot('import-calculated');
		await click('text=Show the functions you can use'); await shot('import-functions');
		await click('button:text-is("Close")').catch(() => {});
	});
	await tab('Mapping'); await shot('import-mapping');
	await tab('Result'); await wait(600); await shot('import-result');
	await tryDo('load list tab', async () => { await click('main button:has-text("Load list")', 900); await shot('import-result-loadlist'); });
	await tryDo('check edits', async () => { await click('button:has-text("Check edits")', 1200); await shot('import-check-edits'); });
	await click('button:text-is("Discard")', 900);
});

group('lists-a', async () => {
	const page = h.page;
	await list('Plant Areas'); await shot('plant-areas');
	await list('Equipment Packages'); await tryDo('expand', () => click('button:has-text("Expand all")')); await shot('equipment-packages');
	await tryDo('type lists', async () => { await click('main button:has-text("Lists")', 1000); await shot('equipment-type-lists'); });
	await tryDo('discard', async () => { const d = vis('main button:text-is("Discard")'); if (await d.isEnabled()) await d.click(); });
	await list('Load Types'); await shot('load-types');
	await tryDo('load type', async () => {
		await click('td:text-is("DOL")', 1200); await shot('load-type-details');
		await inDialog('button:has-text("Cable Schedule")', 900); await shot('load-type-cable-rows');
		await inDialog('button:has-text("PLC I/O List")', 900); await shot('load-type-io-rows');
		await inDialog('button:has-text("Components")', 900); await shot('load-type-components');
		await inDialog('button:has-text("Cable Schedule")', 700); await inDialog('button:has-text("All tags")', 700); await shot('template-tags');
	});
	await list('Equipment Codes'); await shot('equipment-codes');
	await tryDo('code form', async () => { await vis('main .result-table tbody tr').click(); await wait(800); await shot('equipment-code-form'); });
	await list('Instrument Codes'); await shot('instrument-codes');
	await list('Cable Types'); await shot('cable-types');
	await tryDo('cable form', async () => { await vis('main .result-table tbody tr').click(); await wait(800); await shot('cable-type-form'); });
	await list('Motor Data'); await shot('motor-data');
	await tryDo('motor form', async () => { await page.locator('main .result-table tbody tr').filter({ visible: true }).nth(3).click(); await wait(800); await shot('motor-form'); });
	await list('Drive Data'); await shot('drive-data');
	await list('Starter Coordination'); await shot('starter-coordination');
	await list('Load Factors'); await shot('load-factors');
	await list('PLC List'); await shot('plc-list');
	await tryDo('plc types', async () => { await click('main button:has-text("Card & rack types")', 900); await shot('plc-types'); });
});

group('lists-b', async () => {
	const page = h.page;
	await list('MEL'); await shot('mel-list');
	await list('Electrical Equipment List'); await shot('eel');
	await tryDo('eel form', async () => { await click(row('MCC-1'), 900); await shot('eel-form'); });
	await list('Distribution Panels'); await shot('panel-switchboard');
	await tryDo('sld', async () => { await click('button:has-text("Single line diagram")', 1200); await shot('panel-sld'); await click('button:has-text("Switchboard")'); });
	await tryDo('discard', async () => { const d = vis('main button:text-is("Discard")'); if (await d.isEnabled()) await d.click(); });
	await list('Instrument Runsheet'); await shot('instrument-runsheet');
	await list('PID Symbols'); await shot('pid-symbols');
	await tryDo('loops', async () => { await click('main button:has-text("Loops")', 1000); await shot('pid-loops'); });
	await list('Instrument Types'); await shot('instrument-types');
	await list('Drawing List'); await shot('drawing-list');
	await tryDo('drawing form', async () => { await vis('main .result-table tbody tr').click(); await wait(800); await shot('drawing-form'); });
	await list('Document List'); await shot('document-list');
	await list('Enums'); await shot('enums');
});

group('loadlist', async () => {
	const page = h.page;
	await list('Load List'); await shot('load-list');
	await tryDo('fields', async () => {
		await click('button:has-text("Edit fields")', 1200); await shot('load-fields');
		await tryDo('calc', async () => { await inDialog('button:has-text("+ Add calculated field")', 700); await page.locator('dialog[open] button:has-text("Formula")').filter({ visible: true }).last().click(); await wait(900); await shot('load-calculated-field'); });
	});
	await tryDo('set', async () => { await click('button:has-text("Set cable details")', 900); await shot('load-set-cable'); });
	await tryDo('factors', async () => { await click('button:has-text("Set load factors")', 900); await shot('load-set-factors'); });
	await tryDo('reset', async () => { await click('button:has-text("Reset…")', 900); await shot('load-reset'); });
	await list('Load List Summary'); await shot('load-summary');
	await tryDo('summary edit', async () => { await click('button:has-text("Edit tables")', 800); await click('button:has-text("+ Table")', 800); await shot('load-summary-edit'); });
	await list('Cable Schedule'); await shot('master-cable-schedule');
	await tryDo('columns', async () => { await click('button:has-text("Edit columns")', 1000); await shot('master-columns'); });
	await list('IO List'); await shot('master-io-list');
});

group('output', async () => {
	const page = h.page;
	await nav('Generators'); await shot('generators');
	await nav('Deliverables'); await shot('deliverables');
	await tryDo('new', async () => { await click('button:has-text("New deliverable")', 900); await shot('deliverable-new'); });
	await click('text=Sample cable schedule', 1200); await shot('deliverable');
	await tryDo('columns', async () => { await click('button:has-text("Choose and order")', 900); await shot('deliverable-columns'); });
	await tryDo('issue', async () => {
		if (await page.locator('button:has-text("Issue Rev A")').count()) {
			await click('button:has-text("Issue Rev A")', 900);
			await fill('input[placeholder*="Issued for review"]', 'Issued for review');
			await shot('deliverable-issue-dialog');
			await inDialog('button:has-text("Issue Rev A")', 2500);
		}
		await shot('deliverable-issued');
	});
	await nav('Change log'); await shot('change-log');
	await tryDo('details', async () => { await click('main button:text-is("Details") >> nth=0', 800); await shot('change-log-details'); });
	await nav('Projects'); await shot('projects');
});
