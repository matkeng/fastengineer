<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The MEL: every row of the latest file of every MEL import, to read. Nothing is edited here:
// it changes when an import's file or rules change (List import). Rows unticked there as not
// loads are in it too, marked, because other lists refer to that equipment.
import type { ColumnsConfig } from 'datatables.net';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import type { MelRow } from '../../lib/runsheetTypes';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import ListWorkbook from './ListWorkbook.vue';

const kl = useKeyLists();
const ui = useUi();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<MelRow> | null = null;
const mel = computed(() => kl.melList);
const notLoads = computed(() => mel.value?.rows.filter((r) => !r.in_load_list).length ?? 0);

function build() {
	if (!host.value || !mel.value) return;
	table?.api.destroy();
	const m = mel.value;
	const sources = [...new Set(m.rows.map((r) => r.source))];
	const columns: ColumnsConfig[] = [
		{ title: 'Source', data: 'source', render: (v: string, type: string) => (type === 'display' ? escapeHtml(v) : v) },
		{ title: 'Tag', data: 'tag', className: 'key-col', render: (v: string, type: string) => (type === 'display' ? escapeHtml(v) : v) },
		{
			title: 'In the Load List', data: 'in_load_list', className: 'center',
			render: (v: boolean, type: string) => (type !== 'display' ? (v ? 'Yes' : 'No')
				: v ? '<span class="yes">✓</span>' : '<span class="hint" title="Unticked in the import\'s Rows step: not a load">not a load</span>'),
		},
		...m.headers.map((h): ColumnsConfig => ({
			title: escapeHtml(h),
			data: (row: MelRow) => row.values[h] ?? '',
			render: (v: string, type: string) => (type === 'display' ? escapeHtml(v) : v),
		})),
	];
	table = createFilteredTable<MelRow>(host.value, columns.length, {
		data: m.rows,
		columns,
		order: [[0, 'asc'], [1, 'asc']],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible' }, filename: 'MEL' },
		],
		language: { search: 'Search all:', emptyTable: 'No MEL yet. Make a MEL import in List import and upload its file.' },
	}, {
		0: { options: [{ value: '', label: 'All' }, ...sources.map((s) => ({ value: s, label: s }))], test: (v, r) => v === '' || r.source === v },
		2: {
			options: [{ value: '', label: 'All' }, { value: 'y', label: 'In the Load List' }, { value: 'n', label: 'Not a load' }],
			test: (v, r) => v === '' || r.in_load_list === (v === 'y'),
		},
	});
}

watch([mel, host], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-mel">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">MEL</h2>
			<span class="chip">Read only</span>
			<span v-if="mel" class="hint small">
				{{ mel.rows.length }} row(s) from {{ mel.sources.length }} import(s)<template v-if="notLoads"> · {{ notLoads }} not in the Load List</template>
			</span>
			<span class="spacer" />
			<ListWorkbook list-id="mel" name="MEL" export-only />
			<button type="button" class="secondary" :disabled="kl.busy" title="Read the imports again" @click="kl.loadMel()">Refresh</button>
			<button type="button" class="secondary" @click="ui.go('mel')">Open List import</button>
		</div>
		<p v-if="kl.error" class="error">{{ kl.error }}</p>
		<p class="hint small">
			Every row of the latest file of every MEL import, with its columns as the import's column rules leave them. It can't be
			edited here: it changes when a new file is uploaded or an import's rules change, in <strong>List import</strong>. Rows
			unticked there as not loads are shown too (<em>not a load</em>): they are not in the Load List, but other lists, such as the
			Instrument Runsheet, can refer to that equipment.
		</p>
		<p v-for="w in mel?.warnings ?? []" :key="w" class="warn small">{{ w }}</p>
		<div class="results mel-grid"><div ref="host" class="result-table" /></div>
	</section>
</template>
