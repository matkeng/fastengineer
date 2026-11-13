<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// PID Symbols: the symbols found on the P&IDs, one row per detection with its centre (x / y, mm
// from the sheet's top-left). Made from every PID Symbols List Import (sent from Symbol
// Detection runs); read-only here.
import type { ColumnsConfig } from 'datatables.net';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { apiGet } from '../../lib/engine';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import ListWorkbook from './ListWorkbook.vue';
import PidLoopsView from './PidLoopsView.vue';

type Row = Record<string, string | number | boolean | null>;
interface PidView { fields: string[]; rows: Row[]; sources: { id: string; name: string; rows: number; has_file: boolean }[]; warnings: string[] }
const LABELS: Record<string, string> = {
	tag: 'Tag', function: 'Function', loop: 'Loop', suffix: 'Suffix', symbol: 'Symbol', desc: 'Description', drawing: 'Drawing', page: 'Page',
	x_mm: 'X (mm)', y_mm: 'Y (mm)', width_mm: 'Width (mm)', height_mm: 'Height (mm)', score: 'Score', source: 'Detected by', status: 'Status',
	is_deleted: 'Deleted',
};
const MM = new Set(['x_mm', 'y_mm', 'width_mm', 'height_mm']);
const SELECT = new Set(['drawing', 'page', 'symbol', 'source', 'function', 'status']);

const kl = useKeyLists();
const ui = useUi();
const host = ref<HTMLDivElement | null>(null);
const view = ref<PidView | null>(null);
const error = ref('');
const busy = ref(false);
const tab = ref<'detections' | 'loops'>('detections');
const loopsView = ref<InstanceType<typeof PidLoopsView> | null>(null);
let table: FilteredTable<Row> | null = null;

async function load() {
	busy.value = true;
	error.value = '';
	try {
		view.value = await apiGet<PidView>('/api/pid-symbols');
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	} finally {
		busy.value = false;
	}
}
onMounted(load);
watch(() => kl.overview?.pid_symbols, () => { if (!busy.value) void load(); });

function build() {
	if (!host.value || !view.value) return;
	table?.api.destroy();
	const v = view.value;
	const cols = ['import', ...v.fields];
	const columns = cols.map((f): ColumnsConfig => ({
		title: escapeHtml(f === 'import' ? 'Import' : LABELS[f] ?? f),
		data: (r: Row) => r[f] ?? null,
		className: f === 'tag' ? 'key-col' : typeof v.rows.find((r) => r[f] != null && r[f] !== '')?.[f] === 'number' ? 'dt-right' : '',
		render: (x: string | number | boolean | null, type: string) => {
			if (x === null || x === '') return '';
			if (type === 'sort' || type === 'type') return typeof x === 'number' ? x : String(x).toLowerCase();
			if (typeof x === 'number' && MM.has(f)) return x.toFixed(1);
			if (typeof x === 'boolean') return x ? 'Yes' : 'No';
			return escapeHtml(String(x));
		},
	}));
	const selects: Record<number, SelectFilter<Row>> = {};
	cols.forEach((f, i) => {
		if (f !== 'import' && !SELECT.has(f)) return;
		const get = (r: Row) => String(r[f] ?? '');
		const opts = [...new Set(v.rows.map(get).filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
		selects[i] = { options: [{ value: '', label: 'All' }, ...opts.map((o) => ({ value: o, label: o }))], test: (val, r) => val === '' || get(r) === val };
	});
	table = createFilteredTable<Row>(host.value, columns.length, {
		data: v.rows,
		columns,
		order: [],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: 'PID Symbols' },
		],
		language: { search: 'Search all:', emptyTable: 'No PID symbols yet. In Symbol Detection, analyse the P&IDs and send the run to a PID Symbols list import.' },
	}, selects);
}
watch([view, host], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-pid-symbols">
		<div class="mel-head">
			<span class="kind tree">Master list</span>
			<h2 class="key-title">PID Symbols</h2>
			<span class="chip">Read only</span>
			<span v-if="view" class="hint small">{{ view.rows.length }} symbol(s) from {{ view.sources.length }} import(s)</span>
			<span class="spacer" />
			<ListWorkbook list-id="pid-symbols" name="PID Symbols" export-only />
			<button type="button" class="secondary" :disabled="busy" title="Read the imports again" @click="load(); loopsView?.load()">Refresh</button>
			<button type="button" class="secondary" @click="ui.go('mel')">Open List import</button>
		</div>
		<p v-if="error" class="error">{{ error }}</p>
		<p class="hint small">
			The symbols found on the P&amp;IDs, one row per detection, with where each is: <strong>X</strong> and <strong>Y</strong> are its centre in
			<strong>mm from the sheet's top-left corner</strong> (Y down), with its width and height. It is made from every <strong>PID Symbols</strong>
			List Import: in <strong>Symbol Detection</strong>, analyse the drawings and <em>Send to List import</em>; the import's rules and mapping
			apply. It can't be edited here: it changes when a run is sent again or an import's rules change. <strong>Loops</strong> groups the
			detections by loop number, where each loop is given its <strong>instrument type</strong> (Instrument Types) and ticked as verified.
		</p>
		<div class="sym-tabs" role="tablist">
			<button type="button" role="tab" :aria-selected="tab === 'detections'" :class="{ on: tab === 'detections' }" @click="tab = 'detections'">Detections</button>
			<button type="button" role="tab" :aria-selected="tab === 'loops'" :class="{ on: tab === 'loops' }" @click="tab = 'loops'">Loops</button>
		</div>
		<template v-if="tab === 'detections'">
			<p v-for="w in view?.warnings ?? []" :key="w" class="warn small">{{ w }}</p>
		</template>
		<div v-show="tab === 'detections'" class="results mel-grid"><div ref="host" class="result-table" /></div>
		<PidLoopsView v-if="tab === 'loops'" ref="loopsView" />
	</section>
</template>
