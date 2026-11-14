<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import ListWorkbook from './ListWorkbook.vue';
import type { ColumnsConfig } from 'datatables.net';
import { invoke } from '@tauri-apps/api/core';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { apiGet, runningInTauri } from '../../lib/engine';
import { PHASES, RATING_UNITS, type LoadType, type LoadTypeField } from '../../lib/keyListTypes';
import { useKeyLists } from '../../stores/keylists';
import HistoryButton from '../audit/HistoryButton.vue';
import ListUndoButtons from './ListUndoButtons.vue';
import AppModal from '../common/AppModal.vue';
import LoadTypePage from './LoadTypePage.vue';

// Load types: a grid of every row; a row opens on a page of its own (LoadTypePage), where its
// details, its predefined rows for the deliverable lists and its component tables are edited.
const kl = useKeyLists();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<LoadType> | null = null;
const items = computed(() => kl.loadTypes?.items ?? []);

type Kind = 'text' | 'choice' | 'whole' | 'decimal' | 'yesno' | 'starter';
interface Col { field: LoadTypeField; label: string; kind: Kind; required?: boolean; options?: readonly string[]; hint?: string }
const COLS: Col[] = [
	{ field: 'code', label: 'Code', kind: 'text', required: true },
	{ field: 'name', label: 'Name', kind: 'text', required: true },
	{ field: 'rating_unit', label: 'kW or Amps', kind: 'choice', required: true, options: RATING_UNITS },
	{ field: 'voltage', label: 'Voltage', kind: 'whole', required: true, hint: 'Whole number, e.g. 415' },
	{ field: 'phases', label: 'Phases', kind: 'choice', required: true, options: PHASES },
	{ field: 'from_value', label: 'From value', kind: 'decimal', hint: 'Number' },
	{ field: 'to_value', label: 'To value', kind: 'decimal', hint: 'Number' },
	{ field: 'std_drg', label: 'STD Drg', kind: 'text' },
	{ field: 'bucket_type', label: 'Bucket type', kind: 'text' },
	{ field: 'load_type', label: 'Load type', kind: 'text' },
	{ field: 'field_options', label: 'Field options', kind: 'text' },
	{ field: 'load_qty', label: 'Load qty', kind: 'whole', hint: 'Whole number' },
	{ field: 'starter_chart', label: 'Starter chart', kind: 'starter' },
	{ field: 'multi_load', label: 'Multi load', kind: 'yesno' },
];

function build() {
	if (!host.value || !kl.loadTypes) return;
	table?.api.destroy();
	const columns = COLS.map((c): ColumnsConfig => ({
		title: escapeHtml(c.label) + (c.required ? ' <span class="req" title="Required">*</span>' : ''),
		data: (row: LoadType) => row[c.field] ?? null,
		className: c.kind === 'whole' || c.kind === 'decimal' ? 'dt-right' : c.kind === 'yesno' ? 'center' : c.field === 'code' ? 'key-col' : '',
		render: (v: string | number | boolean | null, type: string) => {
			if (c.kind === 'yesno') return type === 'display' ? (v ? '<span class="yes">✓</span>' : '<span class="no">✗</span>') : v ? 'Yes' : 'No';
			if (c.kind === 'starter' && (v === null || v === '')) return type === 'display' ? `<span class="hint">(default${starters.value.default_chart ? `: ${escapeHtml(starters.value.default_chart)}` : ''})</span>` : '';
			if (v === null || v === '') return '';
			if (type === 'sort' || type === 'type') return c.kind === 'whole' || c.kind === 'decimal' ? Number(v) : String(v).toLowerCase();
			return type === 'display' ? escapeHtml(String(v)) : String(v);
		},
	}));
	// The attached PDF: its name opens it (see onClick).
	columns.push({
		title: 'PDF',
		data: (row: LoadType) => row.pdf?.file_name ?? '',
		className: 'pdf-col',
		render: (name: string, type: string, row: LoadType) => {
			if (type !== 'display') return name.toLowerCase();
			return name ? `<button type="button" class="link pdf-link" data-pdf="${escapeHtml(row.id)}" title="Open ${escapeHtml(name)}">📄 ${escapeHtml(name)}</button>` : '';
		},
	});
	columns.push({
		title: 'Rows',
		data: (row: LoadType) => rowCount(row.rows),
		className: 'dt-right',
		render: (n: number, type: string, row: LoadType) => {
			if (type !== 'display') return n;
			const tip = lists.value.map((l) => `${l.name}: ${row.rows?.[l.key]?.length ?? 0}`).join('\n');
			return n ? `<span title="${escapeHtml(tip)}">${n}</span>` : '<span class="hint" title="No predefined rows: loads of this type add nothing to the deliverables">–</span>';
		},
	});
	const selects: Record<number, SelectFilter<LoadType>> = {};
	COLS.forEach((c, i) => {
		if (c.kind === 'choice') {
			selects[i] = {
				options: [{ value: '', label: 'All' }, ...c.options!.map((o) => ({ value: o, label: o }))],
				test: (v, r) => v === '' || r[c.field] === v,
			};
		} else if (c.kind === 'yesno') {
			selects[i] = {
				options: [{ value: '', label: 'All' }, { value: 'y', label: 'Yes' }, { value: 'n', label: 'No' }],
				test: (v, r) => v === '' || r.multi_load === (v === 'y'),
			};
		}
	});
	selects[COLS.length] = {
		options: [{ value: '', label: 'All' }, { value: 'y', label: 'With PDF' }, { value: 'n', label: 'No PDF' }],
		test: (v, r) => v === '' || !!r.pdf === (v === 'y'),
	};
	table = createFilteredTable<LoadType>(host.value, columns.length, {
		data: items.value,
		columns,
		order: [[0, 'asc']],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible' }, filename: 'Load Types' },
		],
		language: { search: 'Search all:', emptyTable: 'No load types yet. Use "Add load type".' },
	}, selects);
}

// -- the page of one load type ----------------------------------------------------------
// The load type open on its page, in place of the grid (which stays as it was underneath: its
// filters and page are there on the way back). `n` makes a new page each time one is opened.
const page = ref<{ row: LoadType | null; n: number } | null>(null);
const lists = computed(() => kl.templateLists?.lists ?? []);
const rowCount = (rows: LoadType['rows'] | undefined) => Object.values(rows ?? {}).reduce((n, r) => n + r.length, 0);
let opened = 0;
function open(row: LoadType | null) {
	kl.error = null;
	page.value = { row, n: ++opened };
}
function closePage() {
	page.value = null;
	kl.error = null;
	kl.fieldErrors = {};
}

function onClick(e: MouseEvent) {
	const link = (e.target as HTMLElement).closest<HTMLElement>('[data-pdf]');
	if (link) {
		const row = items.value.find((r) => r.id === link.dataset.pdf);
		if (row?.pdf) void view(row.id, row.pdf.file_name);
		return;
	}
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as LoadType | undefined;
	if (row) open(row);
}

// -- viewing and saving a copy of a PDF --------------------------------------------------
const viewer = ref<{ id: string; name: string; url: string } | null>(null);

async function view(id: string, name: string) {
	const blob = await kl.loadTypePdf(id);
	if (!blob) return;
	closeViewer();
	viewer.value = { id, name, url: URL.createObjectURL(blob) };
}

function closeViewer() {
	if (viewer.value) URL.revokeObjectURL(viewer.value.url);
	viewer.value = null;
}

async function saveCopy(id: string, name: string) {
	const blob = await kl.loadTypePdf(id);
	if (!blob) return;
	if (runningInTauri) {
		const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
		const path = await saveDialog({ defaultPath: name, filters: [{ name: 'PDF', extensions: ['pdf'] }] });
		if (!path) return;
		try {
			await invoke('save_bytes', { path, bytes: Array.from(new Uint8Array(await blob.arrayBuffer())) });
			kl.message = `Saved ${path}`;
		} catch (err) {
			kl.error = String(err);
		}
	} else {
		const url = URL.createObjectURL(blob);
		Object.assign(document.createElement('a'), { href: url, download: name }).click();
		setTimeout(() => URL.revokeObjectURL(url), 10_000);
	}
}

watch(() => [host.value, kl.loadTypes, kl.templateLists], build);
onMounted(() => void kl.loadTemplateLists());
// the Starter Coordination charts, for the Starter chart choice
const starters = ref<{ charts: string[]; default_chart: string }>({ charts: [], default_chart: '' });
async function loadStarters() {
	try {
		const got = await apiGet<{ items: { chart: string }[]; default_chart: string }>('/api/keylists/starters');
		starters.value = { charts: [...new Set(got.items.map((s) => s.chart))], default_chart: got.default_chart };
	} catch { /* the choice just lists None and the default */ }
}
onMounted(loadStarters);
watch(() => kl.overview?.starters, loadStarters);
onBeforeUnmount(() => {
	table?.api.destroy();
	closeViewer();
});
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-loads">
		<div v-show="!page" class="key-loads-list">
			<div class="mel-head">
				<span class="kind tree">Key list</span>
				<h2 class="key-title">Load Types</h2>
				<span class="hint small" title="Load types can share a code when their From–To ranges (same unit) don't overlap or touch. A load gets the type of its code whose unit is its Load units (HP counts as kW) and whose range includes its rating.">
					{{ items.length }} load type(s). Click a row to open it. A load is matched on <strong>code, rating unit and From–To range</strong>.</span>
				<span class="spacer" />
				<ListUndoButtons list="load-types" />
				<HistoryButton entity="load_types" record-id="load-types" label="Load Types" />
				<ListWorkbook list-id="load-types" name="Load Types" />
				<button type="button" @click="open(null)">Add load type</button>
			</div>
			<p v-if="kl.error && !page" class="error">{{ kl.error }}</p>
			<div class="results mel-grid">
				<div ref="host" class="result-table ref-rows" @click="onClick" />
			</div>
		</div>

		<LoadTypePage v-if="page" :key="page.n" :row="page.row" :starters="starters" @close="closePage" @view="view" @copy="saveCopy" />

		<AppModal class="pdf-viewer" :open="!!viewer" :title="viewer?.name ?? ''" @close="closeViewer">
			<iframe v-if="viewer" :src="viewer.url" :title="viewer.name" />
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="viewer && saveCopy(viewer.id, viewer.name)">Save a copy</button>
				<button type="button" @click="closeViewer">Close</button>
			</template>
		</AppModal>
	</section>
</template>
