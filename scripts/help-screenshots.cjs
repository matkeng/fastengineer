// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Captures the screenshots of the in-app help (web/src/help/img) from the app running on its sample data.
//
//   1. Start an engine on a NEW, empty data folder and the front end:
//        .venv/bin/python -m workbench_desktop --port 8765 --data-dir /tmp/help-data
//        (cd web && npm run dev)
//   2. node scripts/help-screenshots.cjs            every screenshot
//      node scripts/help-screenshots.cjs import     only the groups whose name starts with "import"
//
// It needs Playwright with Chromium (npm i -g playwright). The steps change the project (they load
// the sample data, analyse the sample P&ID, issue a revision…), which is why the data folder is a new one.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const URL = process.env.HELP_APP_URL || 'http://127.0.0.1:5173/?user=demo';
const OUT = path.join(__dirname, '..', 'web', 'src', 'help', 'img');
// Captured into a temporary folder and copied at the end: a new file under web/src makes the dev
// server reload the page, which would close whatever the step had open.
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'help-shots-'));
const only = process.argv[2] || '';

let page;
const wait = (ms) => page.waitForTimeout(ms);
/** A screenshot of the window, or of one element (`sel`), into web/src/help/img/<name>.png. */
async function shot(name, sel, pad = 6) {
	const file = path.join(TMP, `${name}.png`);
	if (!sel) return page.screenshot({ path: file, clip: { x: 0, y: 0, width: 1280, height: 776 } }); // without the status bar
	const box = await page.locator(sel).first().boundingBox();
	const x = Math.max(0, box.x - pad), y = Math.max(0, box.y - pad);
	return page.screenshot({ path: file, clip: { x, y, width: Math.min(1280 - x, box.width + 2 * pad), height: Math.min(800 - y, box.height + 2 * pad) } });
}
const nav = async (label) => { await page.click(`nav.menubar button:has-text("${label}")`); await wait(900); };
/** Open one of the Project lists by its name in the sidebar. */
const list = async (name) => { await nav('Project lists'); await page.click(`.ref-side li:has(.name:text-is("${name}"))`); await wait(1300); };
/** The first VISIBLE element (the lists of other sections stay in the page, hidden); inside the open dialog when there is one. */
const vis = (sel) => page.locator(sel).filter({ visible: true }).first();
const target = async (sel) => {
	const inside = page.locator('dialog[open]').locator(sel).filter({ visible: true });
	if (await inside.count()) return inside.first();
	return vis(sel);
};
const click = async (sel, ms = 700) => { await (await target(sel)).click({ timeout: 6000 }); await wait(ms); };
const fill = async (sel, text) => (await target(sel)).fill(text, { timeout: 6000 });
const esc = async () => { await page.keyboard.press('Escape'); await wait(300); };

const groups = {};
const group = (name, fn) => { groups[name] = fn; };
module.exports = { group, shot, nav, list, click, fill, vis, esc, wait, get page() { return page; } };
require('./help-screenshots.steps.cjs');

(async () => {
	const browser = await chromium.launch();
	page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
	page.on('dialog', (d) => d.accept());
	let failed = 0;
	for (const [name, fn] of Object.entries(groups)) {
		if (only && !name.startsWith(only) && name !== 'setup') continue;
		try {
			await page.goto(URL);
			await page.waitForSelector('nav.menubar button');
			await wait(1200);
			await fn();
			console.log('ok  ', name);
		} catch (e) {
			failed++;
			console.log('FAIL', name, String(e.message).split('\n').slice(0, 3).join(' ').replace(/\u001b\[\d+m/g, '').slice(0, 260));
			await page.screenshot({ path: path.join(require('os').tmpdir(), `help-fail-${name}.png`) }).catch(() => {});
		}
	}
	await browser.close();
	fs.mkdirSync(OUT, { recursive: true });
	const made = fs.readdirSync(TMP).filter((f) => f.endsWith('.png'));
	for (const f of made) fs.copyFileSync(path.join(TMP, f), path.join(OUT, f));
	console.log(`${made.length} screenshot(s) written to ${path.relative(process.cwd(), OUT)}`);
	process.exit(failed ? 1 : 0);
})();
