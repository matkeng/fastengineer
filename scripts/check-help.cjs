// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Checks the in-app help: every link to another page (and its heading), every image, every page's
// heading lines, and that every section and Project list of the app has a page.
//   node scripts/check-help.cjs
const fs = require('fs');
const path = require('path');

const HELP = path.join(__dirname, '..', 'web', 'src', 'help');
const slug = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const plain = (t) => t.replace(/`/g, '').replace(/\*\*/g, '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/&amp;/g, '&');

const pages = {};
for (const file of fs.readdirSync(path.join(HELP, 'pages')).filter((f) => f.endsWith('.md'))) {
	const text = fs.readFileSync(path.join(HELP, 'pages', file), 'utf8');
	const head = /^---\n([\s\S]*?)\n---\n/.exec(text);
	pages[file.replace(/\.md$/, '')] = {
		text,
		meta: head ? Object.fromEntries(head[1].split('\n').map((l) => [l.slice(0, l.indexOf(':')).trim(), l.slice(l.indexOf(':') + 1).trim()])) : null,
		anchors: new Set([...text.matchAll(/^#{2,3} (.+)$/gm)].map((m) => slug(plain(m[1])))),
	};
}
const images = new Set(fs.readdirSync(path.join(HELP, 'img')));
const index = fs.readFileSync(path.join(HELP, 'index.ts'), 'utf8');
const groups = [...index.match(/HELP_GROUPS = \[(.*?)\]/s)[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);

const problems = [];
const used = new Set();
const target = (from, to) => {
	const [page, anchor] = to.split('#');
	if (!pages[page]) problems.push(`${from}: no page "${page}"`);
	else if (anchor && !pages[page].anchors.has(anchor)) problems.push(`${from}: no heading "#${anchor}" on ${page}`);
};
for (const [id, p] of Object.entries(pages)) {
	if (!p.meta?.title || !p.meta.group || !p.meta.order) problems.push(`${id}: needs title, group and order between --- lines`);
	else if (!groups.includes(p.meta.group)) problems.push(`${id}: group "${p.meta.group}" is not in HELP_GROUPS`);
	for (const m of p.text.matchAll(/\]\(help:([^)]+)\)/g)) target(id, m[1]);
	for (const m of p.text.matchAll(/\]\(img\/([^)]+)\)/g)) {
		used.add(m[1]);
		if (!images.has(m[1])) problems.push(`${id}: no image img/${m[1]}`);
	}
	for (const m of p.text.matchAll(/\]\((?!help:|img\/|#|https?:)([^)]+)\)/g)) problems.push(`${id}: link "${m[1]}" is not help:, img/ or a web address`);
}
// The pages the app's screens open (SECTION_HELP and LIST_HELP in index.ts).
for (const m of index.slice(index.indexOf('SECTION_HELP')).matchAll(/:\s*'([a-z0-9#-]+)',/g)) target('index.ts', m[1]);
if (!pages.welcome) problems.push('no welcome page');
const unused = [...images].filter((f) => !used.has(f));

console.log(`${Object.keys(pages).length} pages, ${images.size} images (${used.size} used)`);
if (unused.length) console.log(`not used by any page: ${unused.join(', ')}`);
for (const p of problems) console.log(`PROBLEM ${p}`);
process.exit(problems.length ? 1 : 0);
