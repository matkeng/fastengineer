<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Drive Data: variable speed drives and their ratings (a project starts with the Rockwell
// PowerFlex 755TS range, 200-240 V to 660-690 V, Open, IP54 and Flange, with frame sizes). A grid
// of every drive, filterable; a drive is added or edited in a form and saved from there. A load is
// matched to the smallest drive of its voltage class, Drive enclosure and Drive duty whose amps
// cover its motor's FLC, and its rows reach it as <<Drive.CatNo>>, <<Drive.Frame>>…
import type { ColumnsConfig } from 'datatables.net';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { ApiError, apiGet, apiPostJson, apiPut } from '../../lib/engine';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import HistoryButton from '../audit/HistoryButton.vue';
import AppModal from '../common/AppModal.vue';
import ListWorkbook from './ListWorkbook.vue';

type Drive = Record<string, string | number | boolean | null> & { id: string; cat_no: string; voltage: number; enclosure: string; frame: string };
const API = '/api/keylists/drives';
const kl = useKeyLists();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<Drive> | null = null;
const items = ref<Drive[] | null>(null);
const busy = ref(false);
const error = ref('');
const note = ref('');

// field, title, tag (<<Drive.Tag>>), select filter
const COLS: { field: string; title: string; tag?: string; select?: boolean; text?: boolean }[] = [
	{ field: 'cat_no', title: 'Cat No', tag: 'CatNo', text: true }, { field: 'manufacturer', title: 'Make', select: true, text: true },
	{ field: 'series', title: 'Series', select: true, text: true }, { field: 'voltage', title: 'Voltage', tag: 'Voltage', select: true },
	{ field: 'enclosure', title: 'Enclosure', tag: 'Enclosure', select: true, text: true }, { field: 'frame', title: 'Frame', tag: 'Frame', select: true, text: true },
	{ field: 'nd_amps', title: 'ND Amps', tag: 'NDAmps' }, { field: 'nd_amps_1min', title: 'ND 1 min', tag: 'ND1min' },
	{ field: 'nd_amps_3s', title: 'ND 3 s', tag: 'ND3s' }, { field: 'nd_kw', title: 'ND kW', tag: 'NDkW' }, { field: 'nd_hp', title: 'ND Hp', tag: 'NDHp' },
	{ field: 'hd_amps', title: 'HD Amps', tag: 'HDAmps' }, { field: 'hd_amps_1min', title: 'HD 1 min', tag: 'HD1min' },
	{ field: 'hd_amps_3s', title: 'HD 3 s', tag: 'HD3s' }, { field: 'hd_kw', title: 'HD kW', tag: 'HDkW' }, { field: 'hd_hp', title: 'HD Hp', tag: 'HDHp' },
	{ field: 'nd_amps_208', title: 'ND Amps 208V', tag: 'NDAmps208' }, { field: 'nd_amps_1min_208', title: 'ND 1 min 208V', tag: 'ND1min208' },
	{ field: 'nd_amps_3s_208', title: 'ND 3 s 208V', tag: 'ND3s208' }, { field: 'hd_amps_208', title: 'HD Amps 208V', tag: 'HDAmps208' },
	{ field: 'hd_amps_1min_208', title: 'HD 1 min 208V', tag: 'HD1min208' }, { field: 'hd_amps_3s_208', title: 'HD 3 s 208V', tag: 'HD3s208' },
];
const HIDDEN = new Set(['series', 'manufacturer', 'nd_amps_208', 'nd_amps_1min_208', 'nd_amps_3s_208', 'hd_amps_208', 'hd_amps_1min_208', 'hd_amps_3s_208']);
const distinct = (f: string) => [...new Set((items.value ?? []).map((r) => String(r[f] ?? '')).filter(Boolean))]
	.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

async function load() {
	try {
		items.value = (await apiGet<{ items: Drive[] }>(API)).items;
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	}
}
onMounted(load);
// a workbook import or reset (ListWorkbook) refreshes the project's overview: read the list again
watch(() => kl.overview?.drives, () => { if (!busy.value) void load(); });

function build() {
	if (!host.value || !items.value) return;
	table?.api.destroy();
	const columns = COLS.map((c): ColumnsConfig => ({
		title: escapeHtml(c.title) + (c.field === 'frame' ? '' : ''),
		data: (r: Drive) => r[c.field] ?? null,
		visible: !HIDDEN.has(c.field), // shown with Columns
		className: c.text ? (c.field === 'part_no' ? 'key-col' : '') : 'dt-right',
		render: (v: string | number | null, type: string, r: Drive) => {
			if (v === null || v === '') return '';
			if (type === 'sort' || type === 'type') return typeof v === 'number' ? v : String(v).toLowerCase();
			const text = escapeHtml(String(v));
			return text;
		},
	}));
	const selects: Record<number, SelectFilter<Drive>> = {};
	COLS.forEach((c, i) => {
		if (!c.select) return;
		selects[i] = { options: [{ value: '', label: 'All' }, ...distinct(c.field).map((v) => ({ value: v, label: v }))], test: (v, r) => v === '' || String(r[c.field]) === v };
	});
	table = createFilteredTable<Drive>(host.value, columns.length, {
		data: items.value, columns, order: [] /* the list's own order: the catalogue's, voltage by voltage */, pageLength: 50, lengthMenu: [25, 50, 100, 250],
		layout: TOOLBAR_LAYOUT,
		buttons: [{ extend: 'colvis', text: 'Columns' }, { extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: 'Drive Data' }],
		language: { search: 'Search all:', emptyTable: 'No drives. Use "Add drive" or "Add missing PowerFlex 755TS".' },
	}, selects);
}
watch([host, items], build);
onBeforeUnmount(() => table?.api.destroy());

// -- the form ---------------------------------------------------------------------------
const editing = ref<{ isNew: boolean; form: Record<string, string | boolean> } | null>(null);
const formErrors = ref<Record<string, string>>({});
function open(row: Drive | null) {
	formErrors.value = {};
	error.value = '';
	const form: Record<string, string | boolean> = { id: row?.id ?? newId() };
	for (const c of COLS) form[c.field] = row ? String(row[c.field] ?? '') : '';
	if (!row) Object.assign(form, { enclosure: 'Open', voltage: '400' });
	editing.value = { isNew: !row, form };
}
function onClick(e: MouseEvent) {
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as Drive | undefined;
	if (row) open(row);
}
async function put(list: unknown[], id?: string) {
	busy.value = true;
	error.value = '';
	try {
		items.value = (await apiPut<{ items: Drive[] }>(API, { items: list })).items;
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
	const i = list.findIndex((r) => (r as Drive).id === e.form.id);
	if (i >= 0) list.splice(i, 1, e.form);
	else list.push(e.form);
	if (await put(list, String(e.form.id))) { editing.value = null; note.value = 'Saved'; }
}
async function remove() {
	const e = editing.value;
	if (!e || e.isNew || !items.value || !confirm(`Delete the drive ${e.form.cat_no} (${e.form.voltage} V)?`)) return;
	if (await put(items.value.filter((r) => r.id !== e.form.id))) editing.value = null;
}
async function addDefaults() {
	busy.value = true;
	try {
		const before = items.value?.length ?? 0;
		items.value = (await apiPostJson<{ items: Drive[] }>(`${API}/defaults`, {})).items;
		note.value = items.value.length > before ? `Added ${items.value.length - before} PowerFlex 755TS drive(s)` : 'Every PowerFlex 755TS drive is already in the list';
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
	<section class="card wizard ref-editor rows-mode key-codes key-drives">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Drive Data</h2>
			<span class="hint small">{{ count }} drive(s). Click a row to edit or delete it.</span>
			<span class="spacer" />
			<span v-if="note" class="saved">✓ {{ note }}</span>
			<button type="button" class="secondary" :disabled="busy" title="Add back any of the PowerFlex 755TS drives that are not in the list; nothing else changes" @click="addDefaults">Add missing PowerFlex 755TS</button>
			<HistoryButton entity="drives" record-id="drives" label="Drive Data" />
			<ListWorkbook list-id="drives" name="Drive Data" />
			<button type="button" @click="open(null)">Add drive</button>
		</div>
		<p v-if="error && !editing" class="error">{{ error }}</p>
		<p class="hint small">
			Starts with the <strong>Rockwell PowerFlex 755TS</strong> drives (publication 750-TD104F, pages 8–21): 200…240 V (amps also at 208 V),
			380…400 V, 480 V, 575…600 V and 660…690 V, each Open (IP00/IP20), IP54 (Type 12) and Flange mount, with their frame sizes. A load gets
			the smallest drive of its voltage class and <strong>Drive enclosure</strong> (blank: Open) whose continuous amps at its <strong>Drive duty</strong>
			(ND or HD; blank: Normal Duty) cover its motor's FLC (Motor Data), else its kW. Its rows reach it as <code>&lt;&lt;Drive.CatNo&gt;&gt;</code>,
			<code>&lt;&lt;Drive.Frame&gt;&gt;</code>, <code>&lt;&lt;Drive.Amps&gt;&gt;</code> (at its duty), <code>&lt;&lt;Drive.NDAmps&gt;&gt;</code>…
		</p>
		<div class="results mel-grid">
			<div ref="host" class="result-table ref-rows" @click="onClick" />
		</div>

		<AppModal :open="!!editing" :title="editing?.isNew ? 'Add drive' : `Drive ${editing?.form.cat_no}`" @close="editing = null">
			<form v-if="editing" class="form-grid two-col motor-form drive-form" @submit.prevent="save">
				<label v-for="c in COLS" :key="c.field" class="field">
					<span>{{ c.title }}<span v-if="['cat_no', 'voltage', 'nd_amps'].includes(c.field)" class="req"> *</span>
						<code v-if="c.tag" class="hint small">&lt;&lt;Drive.{{ c.tag }}&gt;&gt;</code></span>
					<select v-if="c.field === 'enclosure'" v-model="editing.form.enclosure"><option>Open</option><option>IP54</option><option>Flange</option></select>
					<select v-else-if="c.field === 'voltage'" v-model="editing.form.voltage"><option v-for="v in ['240', '400', '480', '600', '690']" :key="v" :value="v">{{ v }}</option></select>
					<input v-else v-model="(editing.form[c.field] as string)" type="text" :class="{ invalid: formErrors[c.field] }" :inputmode="c.text ? undefined : 'decimal'" />
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
