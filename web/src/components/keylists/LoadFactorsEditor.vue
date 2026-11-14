<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Load Factors: load and demand factors by equipment type (a project starts with the typical
// factors and a Default row). A load is matched on its Equipment type (ignoring case); a type
// that isn't listed gets the Default row. Reached as <<LoadFactor.NameplateLF>>, <<LoadFactor.AvgDemand>>…
import type { ColumnsConfig } from 'datatables.net';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { ApiError, apiGet, apiPostJson, apiPut } from '../../lib/engine';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import HistoryButton from '../audit/HistoryButton.vue';
import UndoButtons from '../common/UndoButtons.vue';
import { useSavedUndo } from '../../lib/history';
import AppModal from '../common/AppModal.vue';
import ListWorkbook from './ListWorkbook.vue';

type Row = Record<string, string | number | boolean | null> & { id: string; equipment_type: string };
const API = '/api/keylists/load-factors';
const kl = useKeyLists();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<Row> | null = null;
const items = ref<Row[] | null>(null);
const busy = ref(false);
const error = ref('');
const note = ref('');

// field, title, tag (<<LoadFactor.Tag>>)
const COLS: { field: string; title: string; tag?: string; select?: boolean; text?: boolean }[] = [
	{ field: 'equipment_type', title: 'Equipment Type', tag: 'EquipmentType', text: true },
	{ field: 'nameplate_lf', title: 'Plant Nameplate Load Factor', tag: 'NameplateLF' },
	{ field: 'optimised_lf', title: 'Plant Optimised Load Factor', tag: 'OptimisedLF' },
	{ field: 'avg_demand', title: 'Average Demand Factor', tag: 'AvgDemand' },
	{ field: 'max_demand', title: 'Max Demand Factor', tag: 'MaxDemand' },
	{ field: 'notes', title: 'Notes', tag: 'Notes', text: true },
];
const HIDDEN = new Set<string>();
const distinct = (f: string) => [...new Set((items.value ?? []).map((r) => String(r[f] ?? '')).filter(Boolean))]
	.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

async function load() {
	try {
		items.value = (await apiGet<{ items: Row[] }>(API)).items;
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	}
}
onMounted(load);
// a workbook import or reset (ListWorkbook) refreshes the project's overview: read the list again
watch(() => kl.overview?.load_factors, () => { if (!busy.value) void load(); });

function build() {
	if (!host.value || !items.value) return;
	table?.api.destroy();
	const columns = COLS.map((c): ColumnsConfig => ({
		title: escapeHtml(c.title),
		data: (r: Row) => r[c.field] ?? null,
		visible: !HIDDEN.has(c.field), // shown with Columns
		className: c.text ? (c.field === 'equipment_type' ? 'key-col' : '') : 'dt-right',
		render: (v: string | number | null, type: string, r: Row) => {
			if (v === null || v === '') return '';
			if (type === 'sort' || type === 'type') return typeof v === 'number' ? v : String(v).toLowerCase();
			const text = escapeHtml(String(v));
			if (type === 'display' && c.field === 'equipment_type' && String(v).toLowerCase() === 'default') return `<strong title="Used for any equipment type not in the list">${text}</strong>`;
			return typeof v === 'number' && type === 'display' ? v.toFixed(2) : text;
		},
	}));
	const selects: Record<number, SelectFilter<Row>> = {};
	COLS.forEach((c, i) => {
		if (!c.select) return;
		selects[i] = { options: [{ value: '', label: 'All' }, ...distinct(c.field).map((v) => ({ value: v, label: v }))], test: (v, r) => v === '' || String(r[c.field]) === v };
	});
	table = createFilteredTable<Row>(host.value, columns.length, {
		data: items.value, columns, order: [] /* the list's own order */, pageLength: 50, lengthMenu: [25, 50, 100, 250],
		layout: TOOLBAR_LAYOUT,
		buttons: [{ extend: 'colvis', text: 'Columns' }, { extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: 'Load Factors' }],
		language: { search: 'Search all:', emptyTable: 'No rows. Use "Add row" or "Add missing typical rows".' },
	}, selects);
}
watch([host, items], build);
onBeforeUnmount(() => table?.api.destroy());

// -- the form ---------------------------------------------------------------------------
const editing = ref<{ isNew: boolean; form: Record<string, string | boolean> } | null>(null);
const formErrors = ref<Record<string, string>>({});
function open(row: Row | null) {
	formErrors.value = {};
	error.value = '';
	const form: Record<string, string | boolean> = { id: row?.id ?? newId() };
	for (const c of COLS) form[c.field] = row ? String(row[c.field] ?? '') : '';
	
	editing.value = { isNew: !row, form };
}
function onClick(e: MouseEvent) {
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as Row | undefined;
	if (row) open(row);
}
// Undo: every change is saved at once, so undo saves the list as it was before it.
const hist = useSavedUndo<unknown[]>(() => items.value, (earlier) => put(earlier, undefined, true));
async function step(redo = false) {
	note.value = await hist.step(redo);
}
async function put(list: unknown[], id?: string, undoing = false) {
	busy.value = true;
	error.value = '';
	const before = items.value ? [...items.value] : null;
	try {
		items.value = (await apiPut<{ items: Row[] }>(API, { items: list })).items;
		if (before && !undoing) hist.saved(before);
		await kl.refresh();
		return true;
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
		if (err instanceof ApiError && id) {
			formErrors.value = Object.fromEntries(Object.entries(err.fields).filter(([k]) => k.startsWith(`${id}.`)).map(([k, v]) => [k.slice(id.length + 1), v]));
		}
		return false;
	} finally {
		busy.value = false;
	}
}
async function save() {
	const e = editing.value;
	if (!e || !items.value) return;
	const list: unknown[] = [...items.value];
	const i = list.findIndex((r) => (r as Row).id === e.form.id);
	if (i >= 0) list.splice(i, 1, e.form);
	else list.push(e.form);
	if (await put(list, String(e.form.id))) { editing.value = null; note.value = 'Saved'; }
}
async function remove() {
	const e = editing.value;
	if (!e || e.isNew || !items.value || !confirm(`Delete the row ${e.form.equipment_type}?`)) return;
	if (await put(items.value.filter((r) => r.id !== e.form.id))) editing.value = null;
}
async function addDefaults() {
	busy.value = true;
	try {
		const before = items.value?.length ?? 0;
		const was = items.value ? [...items.value] : null;
		items.value = (await apiPostJson<{ items: Row[] }>(`${API}/defaults`, {})).items;
		if (was) hist.saved(was);
		note.value = items.value.length > before ? `Added ${items.value.length - before} typical row(s)` : 'Every typical row is already in the list';
		await kl.refresh();
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	} finally {
		busy.value = false;
	}
}
const count = computed(() => items.value?.length ?? 0);
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-codes key-load-factors">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Load Factors</h2>
			<span class="hint small">{{ count }} row(s). Click a row to edit or delete it.</span>
			<span class="spacer" />
			<span v-if="note" class="saved">✓ {{ note }}</span>
			<button type="button" class="secondary" :disabled="busy" title="Add back any of the typical rows (and Default) that are not in the list; nothing else changes" @click="addDefaults">Add missing typical rows</button>
			<UndoButtons :can-undo="hist.canUndo.value" :can-redo="hist.canRedo.value" :disabled="busy" @undo="step()" @redo="step(true)" />
			<HistoryButton entity="load_factors" record-id="load-factors" label="Load Factors" />
			<ListWorkbook list-id="load-factors" name="Load Factors" />
			<button type="button" @click="open(null)">Add row</button>
		</div>
		<p v-if="error && !editing" class="error">{{ error }}</p>
		<p class="hint small">
			Load and demand factors by <strong>equipment type</strong>. A load is matched on its <strong>Equipment type</strong> (Load List field,
			ignoring case and extra spaces); a type that isn't listed gets the <strong>Default</strong> row. Its rows and calculated fields reach them as
			<code>&lt;&lt;LoadFactor.NameplateLF&gt;&gt;</code>, <code>&lt;&lt;LoadFactor.OptimisedLF&gt;&gt;</code>, <code>&lt;&lt;LoadFactor.AvgDemand&gt;&gt;</code>,
			<code>&lt;&lt;LoadFactor.MaxDemand&gt;&gt;</code> and <code>&lt;&lt;LoadFactor.Matched&gt;&gt;</code> (No when the Default row was used),
			e.g. a calculated field <code>&lt;&lt;rating&gt;&gt; * &lt;&lt;LoadFactor.NameplateLF&gt;&gt; * &lt;&lt;LoadFactor.AvgDemand&gt;&gt;</code>.
		</p>
		<div class="results mel-grid">
			<div ref="host" class="result-table ref-rows" @click="onClick" />
		</div>

		<AppModal :open="!!editing" :title="editing?.isNew ? 'Add load factor row' : `${editing?.form.equipment_type}`" @close="editing = null">
			<form v-if="editing" class="form-grid two-col motor-form" @submit.prevent="save">
				<label v-for="c in COLS" :key="c.field" class="field">
					<span>{{ c.title }}<span v-if="c.field === 'equipment_type'" class="req"> *</span>
						<code v-if="c.tag" class="hint small">&lt;&lt;LoadFactor.{{ c.tag }}&gt;&gt;</code></span>
					<input v-model="(editing.form[c.field] as string)" type="text" :class="{ invalid: formErrors[c.field] }" :inputmode="c.text ? undefined : 'decimal'" />
					<span v-if="formErrors[c.field]" class="warn small">{{ formErrors[c.field] }}</span>
				</label>
				<button type="submit" hidden />
			</form>
			<p v-if="error" class="error">{{ error }}</p>
			<template #footer>
				<button v-if="editing && !editing.isNew" type="button" class="secondary" :disabled="busy" @click="remove">Delete</button>
				<span class="spacer" />
				<button type="button" class="secondary" @click="editing = null">Cancel</button>
				<button type="button" :disabled="busy" @click="save">Save</button>
			</template>
		</AppModal>
	</section>
</template>
