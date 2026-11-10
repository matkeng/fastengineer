<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import pidSample from '../../../../samples/pid-sample.pdf?url';
import type { Dashboard, DashEvent } from '../../lib/dashboardTypes';
import { apiGet } from '../../lib/engine';
import type { IconName } from '../../lib/icons';
import { useGenerators } from '../../stores/generators';
import { useMel } from '../../stores/mel';
import { useRefData } from '../../stores/refdata';
import { useSymbols } from '../../stores/symbols';
import { type Section, useUi } from '../../stores/ui';
import { useWorkbench } from '../../stores/workbench';
import Icon from '../common/Icon.vue';
import DashChart from './DashChart.vue';

const ui = useUi();
const wb = useWorkbench();
const sym = useSymbols();
const mel = useMel();
const rd = useRefData();
const gens = useGenerators();
const data = ref<Dashboard | null>(null);
const error = ref<string | null>(null);
const busy = ref(false);

async function load() {
	try {
		data.value = await apiGet<Dashboard>('/api/dashboard');
		error.value = null;
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	}
}

const c = computed(() => data.value?.counts);
const empty = computed(() => !!data.value && data.value.recent.length === 0);

function ago(iso: string | null): string {
	if (!iso) return '';
	const s = (Date.now() - new Date(iso).getTime()) / 1000;
	if (s < 60) return 'just now';
	if (s < 3600) return `${Math.floor(s / 60)} min ago`;
	if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
	if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`;
	return new Date(iso).toLocaleDateString();
}

function bytes(n: number): string {
	if (n < 1024) return `${n} B`;
	if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
	if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
	return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

interface Kpi { label: string; icon: IconName; value: string | number; sub: string; tone?: 'ok' | 'warn'; go: Section }
const kpis = computed<Kpi[]>(() => {
	const k = c.value;
	if (!k) return [];
	return [
		{ label: 'Symbol libraries', icon: 'layers', value: k.libraries, sub: `${k.templates} templates`, go: 'symbols' },
		{ label: 'Drawings', icon: 'pages', value: k.drawings, go: 'symbols',
			sub: k.pages ? `${k.pages} pages · ${k.pages_unanalysed ? `${k.pages_unanalysed} not analysed` : 'all analysed'}` : 'none yet',
			tone: k.pages_unanalysed ? 'warn' : undefined },
		{ label: 'Tags found', icon: 'tag', value: k.latest_tags ?? '–', go: 'symbols',
			sub: k.latest_run_at ? `latest analysis, ${ago(k.latest_run_at)}` : 'no analysis yet' },
		{ label: 'List imports', icon: 'recipe', value: k.recipes, go: 'mel',
			sub: `${k.revisions} file revision(s)${k.latest_revision_at ? `, last ${ago(k.latest_revision_at)}` : ''}` },
		{ label: 'Plant areas', icon: 'tree', value: k.plant_areas, go: 'keylists', sub: 'project list' },
		{ label: 'Lists, trees & tables', icon: 'database', value: k.enums + k.trees + k.tables, go: 'ref',
			sub: `${k.enums} lists · ${k.trees} trees · ${k.tables} tables · ${k.rows} rows` },
		{ label: 'Generators', icon: 'generator', value: k.generators, go: 'generators',
			sub: `${k.gen_builds} build(s)${k.latest_build_at ? `, last ${ago(k.latest_build_at)}` : ''}${k.plc_cards ? ` · ${k.plc_panels} PLC panel(s), ${k.plc_cards} cards` : ''}` },
		{ label: 'Engine', icon: 'cpu', value: wb.status === 'ready' ? 'OK' : '–', go: 'engine',
			sub: `${wb.info?.compiled ? 'compiled' : 'Python'}${wb.connectMs !== null ? ` · started in ${wb.connectMs < 1000 ? `${wb.connectMs} ms` : `${(wb.connectMs / 1000).toFixed(1)} s`}` : ''}`,
			tone: wb.status === 'ready' ? 'ok' : 'warn' },
	];
});

interface Starter { title: string; desc: string; icon: IconName; run: () => unknown; featured?: boolean }
const starters = computed<Starter[]>(() => [
	{ title: 'Try the P&ID example', desc: 'Sample drawing + ready-made library', icon: 'play', run: tryExample, featured: empty.value },
	{ title: 'Query an Excel sheet', desc: 'Header row, key column, strikethrough', icon: 'table', run: () => ui.go('excel') },
	{ title: 'Compare two tables', desc: 'Added, deleted, struck and changed', icon: 'compare', run: () => ui.go('compare') },
	{ title: 'Analyse drawings', desc: 'Find symbols and read their tags', icon: 'symbol', run: () => ui.go('symbols') },
	{ title: 'New list import', desc: 'MEL → load list, tags → instruments', icon: 'recipe', run: newImport },
	{ title: 'Lists, trees & tables', desc: 'Your own lists, hierarchies and typed tables', icon: 'tree', run: () => ui.go('ref') },
]);

function newImport() {
	if (mel.draft && mel.dirty && !confirm('Discard unsaved changes to the open list import?')) return;
	if (mel.draft) mel.close();
	ui.go('mel');
}

async function tryExample() {
	busy.value = true;
	try {
		await sym.refresh();
		const lib = sym.libraries.find((l) => l.name.startsWith('P&ID instruments')) ?? (await (async () => {
			await sym.restoreExample();
			return sym.libraries.find((l) => l.name.startsWith('P&ID instruments'));
		})());
		if (!lib) return;
		let d = sym.drawings.find((x) => x.file_name === 'pid-sample.pdf' && x.library_id === lib.id);
		if (!d) d = await sym.upload(await (await fetch(pidSample)).blob(), 'pid-sample.pdf', lib.id);
		if (!d) return;
		sym.libraryId = lib.id;
		if (!sym.checked.includes(d.id)) sym.checked.push(d.id);
		if (sym.show({ kind: 'drawing', id: d.id, page: 1 })) ui.go('symbols');
	} finally {
		busy.value = false;
	}
}

const EVENT_ICON: Record<DashEvent['kind'], IconName> = {
	run: 'run', drawing: 'file', revision: 'upload', recipe: 'recipe', enum: 'enum', tree: 'tree', table: 'table',
	generator: 'generator', build: 'build',
};

async function openEvent(e: DashEvent) {
	if (e.section === 'symbols') {
		await sym.refresh();
		const ok = e.kind === 'run' ? sym.show({ kind: 'run', id: e.id }) : sym.show({ kind: 'drawing', id: e.id, page: 1 });
		if (ok) ui.go('symbols');
	} else if (e.section === 'mel') {
		if (mel.draft?.id !== e.id) {
			if (mel.dirty && !confirm('Discard unsaved changes to the open list import?')) return;
			await mel.open(e.id);
		}
		ui.go('mel');
	} else if (e.section === 'generators') {
		if (gens.draft?.id !== e.id) {
			if (gens.anyDirty && !confirm('Discard unsaved changes to the open generator?')) return;
			await gens.open(e.id);
		}
		if (e.kind === 'build') gens.tab = 'build';
		ui.go('generators');
	} else {
		await rd.refresh();
		await rd.select(e.kind === 'enum' || e.kind === 'tree' ? e.kind : 'table', e.id);
		ui.go('ref');
	}
}

async function openRun(id: string) {
	await sym.refresh();
	if (sym.show({ kind: 'run', id })) ui.go('symbols');
}

onMounted(load);
</script>

<template>
	<div class="dash">
		<div class="dash-head">
			<h2>Dashboard</h2>
			<span class="hint" style="margin: 0">Everything stored on this computer, at a glance.</span>
			<span class="spacer" />
			<button type="button" class="secondary small" @click="load">Refresh</button>
		</div>
		<p v-if="error" class="error">{{ error }}</p>

		<div class="kpis">
			<button v-for="k in kpis" :key="k.label" type="button" class="kpi" @click="ui.go(k.go)">
				<span class="kpi-label"><Icon :name="k.icon" />{{ k.label }}</span>
				<span class="kpi-value">{{ k.value }}</span>
				<span class="kpi-sub" :class="k.tone">{{ k.sub }}</span>
			</button>
		</div>

		<section class="card">
			<h2>Start</h2>
			<div class="starters">
				<button v-for="s in starters" :key="s.title" type="button" class="starter" :class="{ featured: s.featured }" :disabled="busy" @click="s.run()">
					<span class="thumb"><Icon :name="s.icon" /></span>
					<span class="starter-title">{{ s.title }}</span>
					<span class="starter-desc">{{ s.desc }}</span>
				</button>
			</div>
		</section>

		<div class="dash-grid">
			<section class="card">
				<h2>Recent activity</h2>
				<ul v-if="data?.recent.length" class="activity">
					<li v-for="e in data.recent" :key="`${e.kind}-${e.id}-${e.at}`" :title="new Date(e.at).toLocaleString()" @click="openEvent(e)">
						<Icon :name="EVENT_ICON[e.kind]" />
						<span class="what"><div class="title">{{ e.title }}</div><div class="detail">{{ e.detail }}</div></span>
						<span class="when">{{ ago(e.at) }}</span>
					</li>
				</ul>
				<p v-else class="hint">Nothing yet. Start with <button type="button" class="link" @click="tryExample">the P&amp;ID example</button>.</p>
			</section>

			<div class="dash">
				<section class="card">
					<h2>Latest analyses</h2>
					<DashChart :runs="data?.runs ?? []" @open="openRun" />
				</section>
				<section v-if="data" class="card sysinfo">
					<h2>Storage &amp; system</h2>
					<dl>
						<dt>Data folder</dt><dd>{{ data.storage.data_dir }}</dd>
						<dt>Database</dt><dd>{{ bytes(data.storage.database_bytes) }}</dd>
						<dt>Drawings</dt><dd>{{ bytes(data.storage.drawings_bytes) }} · {{ data.storage.page_images }} page images</dd>
						<dt>Open workbooks</dt><dd>{{ data.counts.open_workbooks }}</dd>
						<dt>Engine</dt><dd>{{ wb.info ? `${wb.info.core_version} · ${wb.info.compiled ? 'compiled' : 'Python'} · pid ${wb.info.pid}` : '–' }}</dd>
						<dt>OCR</dt><dd>{{ data.storage.ocr_available ? data.storage.ocr_engine : `not available (${data.storage.ocr_reason})` }}</dd>
					</dl>
				</section>
			</div>
		</div>
	</div>
</template>
