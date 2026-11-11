<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// A Project Master list: every row the Power and Instrument generators make for one list
// (cable schedule, equipment list, instrument list, IO list), worked out when it is opened.
// It is read only: a row changes when what it comes from does. Deliverables are made from it.
import type { ColumnsConfig } from 'datatables.net';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { apiPostJsonForBlob, exportToPath, runningInTauri } from '../../lib/engine';
import { cellText } from '../../lib/genTypes';
import { useDeliverables } from '../../stores/deliverables';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import MasterColumnsEditor from './MasterColumnsEditor.vue';

type Row = { cells: (string | number | boolean | null)[] };
const kl = useKeyLists();
const dl = useDeliverables();
const ui = useUi();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<Row> | null = null;
const m = computed(() => kl.master!);
const summary = computed(() => kl.masters.find((x) => x.key === m.value.key));
const note = ref('');
const editing = ref(false);

/** The columns changed: the row editors, this list and the deliverables pick them up. */
async function columnsSaved() {
	kl.templateLists = null;
	await kl.loadMaster();
	void dl.refresh();
	note.value = 'Columns saved';
}

function build() {
	if (!host.value || !kl.master) return;
	table?.api.destroy();
	const head = m.value.result.header;
	const columns = head.map((h, i): ColumnsConfig => ({
		title: escapeHtml(h),
		data: (row: Row) => row.cells[i] ?? '',
		className: typeof m.value.result.rows[0]?.cells[i] === 'number' ? 'dt-right' : '',
		render: (v: string | number | boolean | null, type: string) => (type === 'display' ? escapeHtml(cellText(v)) : v ?? ''),
	}));
	const selects: Record<number, SelectFilter<Row>> = {};
	for (const [name, values] of [['Generator', ['Power', 'Instrument']], ['Confirmed', ['TRUE', 'FALSE']]] as const) {
		const i = head.indexOf(name);
		if (i >= 0) selects[i] = { options: [{ value: '', label: 'All' }, ...values.map((v) => ({ value: v, label: v }))], test: (v, r) => v === '' || r.cells[i] === v };
	}
	table = createFilteredTable<Row>(host.value, columns.length, {
		data: m.value.result.rows,
		columns,
		order: [],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [{ extend: 'colvis', text: 'Columns' }, { extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible' } }],
		language: { search: 'Search all:', emptyTable: 'No rows yet: nothing comes from the Load List or the Instrument Runsheet for this list.' },
	}, selects);
}

async function exportList(format: 'xlsx' | 'csv') {
	const url = `/api/master/${m.value.key}/export`;
	const file = `${m.value.name}.${format}`;
	note.value = '';
	try {
		if (runningInTauri) {
			const { save } = await import('@tauri-apps/plugin-dialog');
			const path = await save({ defaultPath: file, filters: [format === 'csv' ? { name: 'CSV', extensions: ['csv'] } : { name: 'Excel workbook', extensions: ['xlsx'] }] });
			if (path) note.value = `Saved ${(await exportToPath(url, { format }, path)).path}`;
		} else {
			const href = URL.createObjectURL(await apiPostJsonForBlob(url, { format }));
			Object.assign(document.createElement('a'), { href, download: file }).click();
			setTimeout(() => URL.revokeObjectURL(href), 10_000);
			note.value = `Downloaded ${file}`;
		}
	} catch (err) {
		note.value = err instanceof Error ? err.message : String(err);
	}
}

async function openDeliverables() {
	await dl.refresh();
	ui.go('deliverables');
}

watch([() => kl.master, host], build, { immediate: true, flush: 'post' });
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-master">
		<div class="mel-head">
			<span class="kind tree">Master list</span>
			<h2 class="key-title">{{ m.name }}</h2>
			<span class="chip">Read only</span>
			<span class="hint small">
				{{ m.result.rows.length }} row(s)<template v-if="summary"> · {{ summary.power_rows }} from Power · {{ summary.instrument_rows }} from Instrument</template>
			</span>
			<span class="spacer" />
			<span v-if="note" class="saved" :title="note">{{ note }}</span>
			<button type="button" class="secondary" title="Rename, add, delete or reorder the columns of the master lists" @click="editing = true">Edit columns…</button>
			<button type="button" class="secondary" @click="exportList('xlsx')">Export .xlsx</button>
			<button type="button" class="secondary" @click="exportList('csv')">CSV</button>
			<button type="button" class="secondary" :disabled="kl.busy" title="Work it out again" @click="kl.loadMaster()">Refresh</button>
			<button type="button" @click="openDeliverables">Deliverables</button>
		</div>
		<p v-if="kl.error" class="error">{{ kl.error }}</p>
		<p class="hint small">
			Every row the generators make for this list, worked out now: <strong>Power</strong> adds the rows of each load's load type,
			<strong>Instrument</strong> the rows of each Instrument Runsheet row's equipment type. It can't be edited here: change the Load
			List, Load Types, Equipment Packages or Instrument Runsheet and it follows. Its columns are the project's: <strong>Edit columns…</strong>
			renames, adds, deletes or reorders them. A <strong>{{ m.deliverable_type }}</strong> deliverable
			takes its rows from it, through a filter and a choice of columns, and is what gets issued in revisions.
		</p>
		<p v-if="m.missing_load_types.length" class="warn small">
			{{ m.missing_load_types.length }} load(s) have no load type and add nothing yet: {{ m.missing_load_types.slice(0, 10).join(', ') }}{{ m.missing_load_types.length > 10 ? '…' : '' }}
		</p>
		<p v-for="w in m.warnings" :key="w" class="warn small">{{ w }}</p>
		<div class="results mel-grid"><div ref="host" class="result-table" /></div>
		<MasterColumnsEditor :open="editing" :list-key="m.key" @close="editing = false" @saved="columnsSaved" />
	</section>
</template>
