<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Instrument Types: what an instrument loop on the P&IDs is (Level Transmitter, Density
// Transmitter, 2 x Conveyor Drift Switch…), each with the P&ID function codes of its tags
// (DE, DX, DIT). The PID Symbols list's Loops view suggests a loop's type from its functions.
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

type Row = Record<string, string | number | boolean | null | string[]> & { id: string; name: string; functions: string[] };
const API = '/api/keylists/instrument-types';
const kl = useKeyLists();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<Row> | null = null;
const items = ref<Row[] | null>(null);
const busy = ref(false);
const error = ref('');
const note = ref('');

// field, title
const COLS: { field: string; title: string; tag?: string; select?: boolean; text?: boolean }[] = [
	{ field: 'name', title: 'Instrument type', text: true },
	{ field: 'functions', title: 'P&ID function codes', text: true },
	{ field: 'description', title: 'Description', text: true },
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
watch(() => kl.overview?.instrument_types, () => { if (!busy.value) void load(); });

function build() {
	if (!host.value || !items.value) return;
	table?.api.destroy();
	const columns = COLS.map((c): ColumnsConfig => ({
		title: escapeHtml(c.title),
		data: (r: Row) => (Array.isArray(r[c.field]) ? (r[c.field] as string[]).join(', ') : r[c.field] ?? null),
		visible: !HIDDEN.has(c.field), // shown with Columns
		className: c.text ? (c.field === 'name' ? 'key-col' : '') : 'dt-right',
		render: (v: string | number | null | string[], type: string, r: Row) => {
			if (v === null || v === '') return '';
			if (type === 'sort' || type === 'type') return typeof v === 'number' ? v : String(v).toLowerCase();
			const text = escapeHtml(String(v));
			return c.field === 'functions' && type === 'display' ? `<code>${text}</code>` : text;
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
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: 'Instrument Types' }],
		language: { search: 'Search all:', emptyTable: 'No instrument types. Use "Add type" or "Add missing common types".' },
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
	for (const c of COLS) form[c.field] = row ? (Array.isArray(row[c.field]) ? (row[c.field] as string[]).join(', ') : String(row[c.field] ?? '')) : '';
	
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
	if (!e || e.isNew || !items.value || !confirm(`Delete the instrument type ${e.form.name}?`)) return;
	if (await put(items.value.filter((r) => r.id !== e.form.id))) editing.value = null;
}
async function addDefaults() {
	busy.value = true;
	try {
		const before = items.value?.length ?? 0;
		const was = items.value ? [...items.value] : null;
		items.value = (await apiPostJson<{ items: Row[] }>(`${API}/defaults`, {})).items;
		if (was) hist.saved(was);
		note.value = items.value.length > before ? `Added ${items.value.length - before} common type(s)` : 'Every common type is already in the list';
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
	<section class="card wizard ref-editor rows-mode key-codes key-instrument-types">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Instrument Types</h2>
			<span class="hint small">{{ count }} type(s). Click a row to edit or delete it.</span>
			<span class="spacer" />
			<span v-if="note" class="saved">✓ {{ note }}</span>
			<button type="button" class="secondary" :disabled="busy" title="Add back any of the common ISA types that are not in the list; nothing else changes" @click="addDefaults">Add missing common types</button>
			<UndoButtons :can-undo="hist.canUndo.value" :can-redo="hist.canRedo.value" :disabled="busy" @undo="step()" @redo="step(true)" />
			<HistoryButton entity="instrument_types" record-id="instrument-types" label="Instrument Types" />
			<ListWorkbook list-id="instrument-types" name="Instrument Types" />
			<button type="button" @click="open(null)">Add type</button>
		</div>
		<p v-if="error && !editing" class="error">{{ error }}</p>
		<p class="hint small">
			What an instrument loop on the P&amp;IDs is, with the <strong>P&amp;ID function codes</strong> of its tags: a Density Transmitter is
			<code>DE, DX, DIT</code> (element, source, transmitter). A code belongs to one type only. In <strong>PID Symbols → Loops</strong>
			each loop is given the type that shares the most function codes with its tags, until you choose one.
		</p>
		<div class="results mel-grid">
			<div ref="host" class="result-table ref-rows" @click="onClick" />
		</div>

		<AppModal :open="!!editing" :title="editing?.isNew ? 'Add instrument type' : `${editing?.form.name}`" @close="editing = null">
			<form v-if="editing" class="form-grid two-col motor-form" @submit.prevent="save">
				<label v-for="c in COLS" :key="c.field" class="field">
					<span>{{ c.title }}<span v-if="c.field === 'name'" class="req"> *</span></span>
					<input v-model="(editing.form[c.field] as string)" type="text" :class="{ invalid: formErrors[c.field] }"
						:placeholder="c.field === 'functions' ? 'e.g. DE, DX, DIT' : ''" />
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
