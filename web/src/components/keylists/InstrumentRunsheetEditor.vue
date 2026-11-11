<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The Instrument Runsheet: one row per instrument assembly, in a spreadsheet grid (type, or
// paste from Excel). A row names an equipment type, a plant area and its parent equipment;
// all three must exist before the list can be saved, so a cell that matches nothing is marked
// as soon as it is typed. The rest of the row is what the equipment type's rows are filled
// in with: suffix, P&ID, marshalling box, confirmed, PLC rack and the numbers #1 to #35.
import { computed, ref } from 'vue';
import { newId } from '../../lib/genTypes';
import { filledRows, runsheetProblems, type TypedRow } from '../../lib/runsheetTypes';
import { useKeyLists } from '../../stores/keylists';
import HistoryButton from '../audit/HistoryButton.vue';
import EditGrid, { type CellEdit, type GridColumn } from '../common/EditGrid.vue';
import ListWorkbook from './ListWorkbook.vue';

const kl = useKeyLists();
const view = computed(() => kl.runsheetView!);
const rows = computed(() => kl.runsheetDraft ?? []);
const n = computed(() => view.value.columns.length);

const columns = computed((): GridColumn[] => view.value.columns.map((c, i) => ({
	label: c.heading, sub: c.tag,
	width: i === 0 ? 280 : i === 2 ? 190 : i === 5 ? 190 : i === 4 ? 150 : i === 1 ? 100 : i === 6 ? 90 : i === 3 || i === 7 ? 120 : 76,
	options: i === 0 ? view.value.equipment_types : i === 1 ? view.value.areas : i === 2 ? view.value.parents : i === 6 ? ['TRUE', 'FALSE'] : undefined,
	title: i === 0 ? 'An equipment type of the Equipment Packages list' : i === 1 ? "A plant area's tag number"
		: i === 2 ? 'A tag in the Electrical Equipment List or the MEL' : c.heading,
	badge: i < 3 ? 'ref' : undefined,
})));
const cells = computed(() => rows.value.map((r) => Array.from({ length: n.value }, (_, c) => r.cells[c] ?? '')));

// Same rules as the engine, so problems show while typing.
const problems = computed(() => ({ ...runsheetProblems(rows.value, view.value), ...kl.fieldErrors }));
const problemCount = computed(() => Object.keys(problems.value).length);
const errorOf = (r: number, c: number) => problems.value[`${rows.value[r]?.id}.${view.value.columns[c]?.key}`];
const cellClass = (r: number, c: number) => (errorOf(r, c) ? 'bad-cell' : '');
const at = ref({ r: 0, c: 0 });
const here = computed(() => errorOf(at.value.r, at.value.c));
const firstProblems = computed(() => {
	const index = new Map(rows.value.map((r, i) => [r.id, i + 1]));
	return Object.entries(problems.value).slice(0, 6).map(([k, m]) => `Row ${index.get(k.split('.')[0]) ?? '?'}: ${m}`);
});
const counts = computed(() => {
	const filled = filledRows(rows.value);
	return { rows: filled.length, confirmed: filled.filter((r) => ['true', 'yes', 'y', '1', 'x'].includes((r.cells[6] ?? '').trim().toLowerCase())).length };
});

const empty = (): TypedRow => ({ id: newId(), cells: Array.from({ length: n.value }, () => '') });
function setCells(edits: CellEdit[]) {
	const list = kl.runsheetDraft;
	if (!list) return;
	for (const e of edits) {
		while (list.length <= e.r) list.push(empty()); // a paste that runs past the last row adds rows
		const row = list[e.r];
		while (row.cells.length < n.value) row.cells.push('');
		if (e.c < n.value) row.cells[e.c] = e.c === 6 && e.value.trim() ? e.value.trim().toUpperCase() : e.value.trim();
	}
}
const insertRows = (index: number, count: number) => kl.runsheetDraft?.splice(index, 0, ...Array.from({ length: count }, empty));
function removeRows(idx: number[]) {
	const drop = new Set(idx);
	if (kl.runsheetDraft) kl.runsheetDraft = kl.runsheetDraft.filter((_, i) => !drop.has(i));
}
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-runsheet">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Instrument Runsheet</h2>
			<span class="hint small">{{ counts.rows }} row(s) · {{ counts.confirmed }} confirmed</span>
			<span class="spacer" />
			<span v-if="problemCount" class="warn small">{{ problemCount }} problem(s)</span>
			<span v-if="kl.runsheetDirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="kl.message" class="saved">✓ {{ kl.message }}</span>
			<HistoryButton entity="instrument_runsheet" record-id="instrument-runsheet" label="Instrument Runsheet" />
			<ListWorkbook list-id="instrument-runsheet" name="Instrument Runsheet" :unsaved="kl.runsheetDirty" />
			<button type="button" class="secondary" :disabled="!kl.runsheetDirty || kl.busy" @click="kl.discard()">Discard</button>
			<button type="button" :disabled="!kl.runsheetDirty || kl.busy || problemCount > 0"
				:title="problemCount ? 'Fix the marked cells first' : ''" @click="kl.saveRunsheet()">Save</button>
		</div>
		<p v-if="kl.error" class="error">{{ kl.error }}</p>
		<p class="hint small">
			The runsheet of the <strong>Instrument generator</strong> (not available yet): each row is an instrument assembly, and the
			tags under the headings are what its equipment type's rows are filled in with. Type in the grid or paste from Excel.
			The three <strong>ref</strong> columns must match before it can be saved: an <strong>equipment type</strong> of Equipment
			Packages, a <strong>plant area</strong> tag number, and a tag in the <strong>Electrical Equipment List</strong> or the
			<strong>MEL</strong>.
		</p>
		<EditGrid :columns="columns" :cells="cells" :cell-class="cellClass" @set="setCells" @insert="insertRows" @remove="removeRows"
			@focus="(r, c) => (at = { r, c })" />
		<p v-if="here" class="warn small runsheet-here">Row {{ at.r + 1 }}, {{ view.columns[at.c]?.heading }}: {{ here }}</p>
		<ul v-else-if="problemCount" class="warn-list">
			<li v-for="m in firstProblems" :key="m">{{ m }}</li>
			<li v-if="problemCount > firstProblems.length">and {{ problemCount - firstProblems.length }} more</li>
		</ul>
		<p v-if="!rows.length" class="hint small">No rows yet. Use “+ Row”, or click the grid and paste rows copied from Excel.</p>
	</section>
</template>
