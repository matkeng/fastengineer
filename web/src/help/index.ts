// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// The in-app help: Markdown pages in ./pages and screenshots in ./img, bundled with the front end.
// A page starts with a few "key: value" lines between --- lines: title, group and order.
// Links between pages are written [text](help:page-id) or (help:page-id#heading); images ![alt](img/name.png).
import { marked } from 'marked';
import type { KeyListId } from '../lib/keyListTypes';
import type { Section } from '../stores/ui';

export interface HelpPage {
	id: string; // the file name without .md
	title: string;
	group: string;
	order: number;
	body: string; // Markdown, without the heading lines
	text: string; // lower-case plain text, for search
}

/** The groups of the contents list, in order. A page in any other group comes last. */
export const HELP_GROUPS = ['Getting started', 'How to', 'Screens', 'Project lists', 'Project master lists', 'Reference'];

const sources = import.meta.glob('./pages/*.md', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const images = import.meta.glob('./img/*.png', { query: '?url', import: 'default', eager: true }) as Record<string, string>;

function parse(path: string, source: string): HelpPage {
	const id = path.replace(/^.*\//, '').replace(/\.md$/, '');
	const meta: Record<string, string> = {};
	let body = source.replace(/\r\n/g, '\n');
	const head = /^---\n([\s\S]*?)\n---\n?/.exec(body);
	if (head) {
		body = body.slice(head[0].length);
		for (const line of head[1].split('\n')) {
			const at = line.indexOf(':');
			if (at > 0) meta[line.slice(0, at).trim()] = line.slice(at + 1).trim();
		}
	}
	const plain = body
		.replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
		.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
		.replace(/[#*`>|_]/g, ' ')
		.replace(/\s+/g, ' ');
	const title = meta.title ?? id;
	return { id, title, group: meta.group ?? 'Reference', order: Number(meta.order ?? 999), body, text: `${title} ${plain}`.toLowerCase() };
}

const groupRank = (g: string) => (HELP_GROUPS.includes(g) ? HELP_GROUPS.indexOf(g) : HELP_GROUPS.length);

/** Every page, in the order of the contents list. */
export const HELP_PAGES: HelpPage[] = Object.entries(sources)
	.map(([path, source]) => parse(path, source))
	.sort((a, b) => groupRank(a.group) - groupRank(b.group) || a.order - b.order || a.title.localeCompare(b.title));

const byId = new Map(HELP_PAGES.map((p) => [p.id, p]));
export const HELP_HOME = 'welcome';
export const helpPage = (id: string): HelpPage | undefined => byId.get(id);

/** The contents list: the groups that have pages, each with its pages. */
export function helpContents(): { group: string; pages: HelpPage[] }[] {
	const out: { group: string; pages: HelpPage[] }[] = [];
	for (const page of HELP_PAGES) {
		const last = out[out.length - 1];
		if (last?.group === page.group) last.pages.push(page);
		else out.push({ group: page.group, pages: [page] });
	}
	return out;
}

/** A page as HTML. Image paths become the bundled files' addresses; help: links are left for the view to follow. */
export function renderHelp(page: HelpPage): string {
	const source = page.body.replace(/\]\(img\/([^)\s]+)\)/g, (whole, name: string) => {
		const url = images[`./img/${name}`];
		return url ? `](${url})` : whole;
	});
	return marked.parse(source, { async: false, gfm: true }) as string;
}

export interface HelpHit { page: HelpPage; snippet: string }

/** Pages that have every word of the query, those with it in the title first. */
export function searchHelp(query: string): HelpHit[] {
	const words = query.toLowerCase().split(/\s+/).filter(Boolean);
	if (!words.length) return [];
	const hits: (HelpHit & { rank: number })[] = [];
	for (const page of HELP_PAGES) {
		if (!words.every((w) => page.text.includes(w))) continue;
		const inTitle = words.every((w) => page.title.toLowerCase().includes(w));
		const at = Math.max(0, page.text.indexOf(words[0], page.title.length) - 50);
		const snippet = (at > 0 ? '…' : '') + page.text.slice(at, at + 170).trim() + '…';
		hits.push({ page, snippet, rank: inTitle ? 0 : 1 });
	}
	return hits.sort((a, b) => a.rank - b.rank);
}

/** The help page for each section of the app... */
export const SECTION_HELP: Record<Section, string> = {
	dashboard: 'dashboard',
	compare: 'compare',
	symbols: 'symbols-libraries',
	mel: 'import-overview',
	keylists: 'working-in-the-app',
	generators: 'generators',
	deliverables: 'deliverables',
	history: 'change-log',
	projects: 'working-in-the-app#choosing-a-project',
	engine: 'troubleshooting',
	help: HELP_HOME,
};

/** ...and for each of the Project lists. */
export const LIST_HELP: Record<KeyListId, string> = {
	'plant-areas': 'plant-areas',
	'equipment-packages': 'equipment-packages',
	'load-types': 'load-types',
	'equipment-codes': 'codes',
	'instrument-codes': 'codes',
	'cable-types': 'cable-types',
	motors: 'motor-data',
	drives: 'drive-data',
	starters: 'starter-coordination',
	'load-factors': 'load-factors',
	plc: 'plc-list',
	mel: 'mel-list',
	eel: 'eel',
	'distribution-panels': 'distribution-panels',
	'instrument-runsheet': 'instrument-runsheet',
	'pid-symbols': 'pid-symbols',
	'instrument-types': 'instrument-types',
	'drawing-list': 'drawing-document-lists',
	'document-list': 'drawing-document-lists',
	enums: 'enums',
	'load-list': 'load-list',
	'load-summary': 'load-summary',
	master: 'master-lists',
};
