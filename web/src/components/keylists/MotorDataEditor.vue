<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Motor Data: motors and their performance data (a project starts with the WEG W22 High
// Efficiency E3 range, 2, 4, 6 and 8 pole, 415 V 50 Hz). A grid of every motor, filterable;
// a motor is added or edited in a form and saved from there. A load is matched to the smallest
// motor of its Poles whose kW is at least its rating, and its rows reach it as <<Motor.FLC>>…
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

type Motor = Record<string, string | number | boolean | null> & { id: string; part_no: string; poles: number; kw: number; design: string; reduced_frame: boolean };
const API = '/api/keylists/motors';
const kl = useKeyLists();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<Motor> | null = null;
const items = ref<Motor[] | null>(null);
const busy = ref(false);
const error = ref('');
const note = ref('');

// field, title, tag (<<Motor.Tag>>), select filter
const COLS: { field: string; title: string; tag?: string; select?: boolean; text?: boolean }[] = [
	{ field: 'part_no', title: 'Part No', tag: 'PartNo', text: true }, { field: 'manufacturer', title: 'Make', select: true, text: true },
	{ field: 'series', title: 'Series', select: true, text: true }, { field: 'poles', title: 'Poles', select: true },
	{ field: 'design', title: 'Design', select: true, text: true }, { field: 'kw', title: 'kW', tag: 'kW' },
	{ field: 'frame', title: 'Frame', tag: 'Frame', text: true }, { field: 'speed', title: 'rpm', tag: 'Speed' },
	{ field: 'flc', title: 'FLC (A)', tag: 'FLC' }, { field: 'il_ir', title: 'IL/Ir', tag: 'ILIr' }, { field: 'torque', title: 'Torque (Nm)', tag: 'Torque' },
	{ field: 'tl_tr', title: 'TL/Tr', tag: 'TLTr' }, { field: 'tb_tr', title: 'Tb/Tr', tag: 'TbTr' },
	{ field: 'eff50', title: 'Eff 50%', tag: 'Eff50' }, { field: 'eff75', title: 'Eff 75%', tag: 'Eff75' }, { field: 'eff100', title: 'Eff 100%', tag: 'Eff100' },
	{ field: 'pf50', title: 'PF 50%', tag: 'PF50' }, { field: 'pf75', title: 'PF 75%', tag: 'PF75' }, { field: 'pf100', title: 'PF 100%', tag: 'PF100' },
	{ field: 'sound', title: 'dB(A)', tag: 'Sound' }, { field: 'inertia', title: 'J (kgm²)', tag: 'Inertia' },
	{ field: 'locked_cold', title: 'Locked cold (s)', tag: 'LockedCold' }, { field: 'locked_hot', title: 'Locked hot (s)', tag: 'LockedHot' },
	{ field: 'weight', title: 'Weight (kg)', tag: 'Weight' }, { field: 'voltage', title: 'V', tag: 'Voltage' }, { field: 'frequency', title: 'Hz' },
];
const distinct = (f: string) => [...new Set((items.value ?? []).map((r) => String(r[f] ?? '')).filter(Boolean))]
	.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

async function load() {
	try {
		items.value = (await apiGet<{ items: Motor[] }>(API)).items;
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	}
}
onMounted(load);
// a workbook import or reset (ListWorkbook) refreshes the project's overview: read the list again
watch(() => kl.overview?.motors, () => { if (!busy.value) void load(); });

function build() {
	if (!host.value || !items.value) return;
	table?.api.destroy();
	const columns = COLS.map((c): ColumnsConfig => ({
		title: escapeHtml(c.title) + (c.field === 'frame' ? '' : ''),
		data: (r: Motor) => r[c.field] ?? null,
		visible: c.field !== 'series', // the same for every W22 motor: shown with Columns
		className: c.text ? (c.field === 'part_no' ? 'key-col' : '') : 'dt-right',
		render: (v: string | number | null, type: string, r: Motor) => {
			if (v === null || v === '') return '';
			if (type === 'sort' || type === 'type') return typeof v === 'number' ? v : String(v).toLowerCase();
			const text = escapeHtml(String(v));
			return type === 'display' && c.field === 'frame' && r.reduced_frame ? `${text}<span title="Output in a reduced frame (High-Output design)">*</span>` : text;
		},
	}));
	const selects: Record<number, SelectFilter<Motor>> = {};
	COLS.forEach((c, i) => {
		if (!c.select) return;
		selects[i] = { options: [{ value: '', label: 'All' }, ...distinct(c.field).map((v) => ({ value: v, label: v }))], test: (v, r) => v === '' || String(r[c.field]) === v };
	});
	table = createFilteredTable<Motor>(host.value, columns.length, {
		data: items.value, columns, order: [[3, 'asc'], [5, 'asc']], pageLength: 50, lengthMenu: [25, 50, 100, 250],
		layout: TOOLBAR_LAYOUT,
		buttons: [{ extend: 'colvis', text: 'Columns' }, { extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: 'Motor Data' }],
		language: { search: 'Search all:', emptyTable: 'No motors. Use "Add motor" or "Add missing WEG W22".' },
	}, selects);
}
watch([host, items], build);
onBeforeUnmount(() => table?.api.destroy());

// -- the form ---------------------------------------------------------------------------
const editing = ref<{ isNew: boolean; form: Record<string, string | boolean> } | null>(null);
const formErrors = ref<Record<string, string>>({});
function open(row: Motor | null) {
	formErrors.value = {};
	error.value = '';
	const form: Record<string, string | boolean> = { id: row?.id ?? newId(), reduced_frame: row?.reduced_frame ?? false };
	for (const c of COLS) form[c.field] = row ? String(row[c.field] ?? '') : '';
	if (!row) Object.assign(form, { design: 'Standard', voltage: '415', frequency: '50' });
	editing.value = { isNew: !row, form };
}
function onClick(e: MouseEvent) {
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as Motor | undefined;
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
		items.value = (await apiPut<{ items: Motor[] }>(API, { items: list })).items;
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
	const i = list.findIndex((r) => (r as Motor).id === e.form.id);
	if (i >= 0) list.splice(i, 1, e.form);
	else list.push(e.form);
	if (await put(list, String(e.form.id))) { editing.value = null; note.value = 'Saved'; }
}
async function remove() {
	const e = editing.value;
	if (!e || e.isNew || !items.value || !confirm(`Delete the motor ${e.form.part_no}?`)) return;
	if (await put(items.value.filter((r) => r.id !== e.form.id))) editing.value = null;
}
async function addDefaults() {
	busy.value = true;
	try {
		const before = items.value?.length ?? 0;
		const was = items.value ? [...items.value] : null;
		items.value = (await apiPostJson<{ items: Motor[] }>(`${API}/defaults`, {})).items;
		if (was) hist.saved(was);
		note.value = items.value.length > before ? `Added ${items.value.length - before} WEG W22 motor(s)` : 'Every WEG W22 motor is already in the list';
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
	<section class="card wizard ref-editor rows-mode key-codes key-motors">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Motor Data</h2>
			<span class="hint small">{{ count }} motor(s). Click a row to edit or delete it.</span>
			<span class="spacer" />
			<span v-if="note" class="saved">✓ {{ note }}</span>
			<button type="button" class="secondary" :disabled="busy" title="Add back any of the WEG W22 motors that are not in the list; nothing else changes" @click="addDefaults">Add missing WEG W22</button>
			<UndoButtons :can-undo="hist.canUndo.value" :can-redo="hist.canRedo.value" :disabled="busy" @undo="step()" @redo="step(true)" />
			<HistoryButton entity="motors" record-id="motors" label="Motor Data" />
			<ListWorkbook list-id="motors" name="Motor Data" />
			<button type="button" @click="open(null)">Add motor</button>
		</div>
		<p v-if="error && !editing" class="error">{{ error }}</p>
		<p class="hint small">
			Starts with the <strong>WEG W22 High Efficiency E3</strong> range (415 V 50 Hz, catalogue pages 24–27; * a reduced frame, High-Output design).
			A load gets the smallest motor of its <strong>Poles</strong> (a Load List field) whose kW is at least its rating (HP is converted; a Standard
			design before a High-Output one), and its rows and calculated fields reach it as <code>&lt;&lt;Motor.PartNo&gt;&gt;</code>,
			<code>&lt;&lt;Motor.FLC&gt;&gt;</code>, <code>&lt;&lt;Motor.Eff100&gt;&gt;</code>, <code>&lt;&lt;Motor.PF100&gt;&gt;</code>, <code>&lt;&lt;Motor.Frame&gt;&gt;</code>…
		</p>
		<div class="results mel-grid">
			<div ref="host" class="result-table ref-rows" @click="onClick" />
		</div>

		<AppModal :open="!!editing" :title="editing?.isNew ? 'Add motor' : `Motor ${editing?.form.part_no}`" @close="editing = null">
			<form v-if="editing" class="form-grid two-col motor-form" @submit.prevent="save">
				<label v-for="c in COLS" :key="c.field" class="field">
					<span>{{ c.title }}<span v-if="['part_no', 'poles', 'kw'].includes(c.field)" class="req"> *</span>
						<code v-if="c.tag" class="hint small">&lt;&lt;Motor.{{ c.tag }}&gt;&gt;</code></span>
					<select v-if="c.field === 'design'" v-model="editing.form.design"><option>Standard</option><option>High-Output</option></select>
					<input v-else v-model="(editing.form[c.field] as string)" type="text" :class="{ invalid: formErrors[c.field] }" :inputmode="c.text ? undefined : 'decimal'" />
					<span v-if="formErrors[c.field]" class="warn small">{{ formErrors[c.field] }}</span>
				</label>
				<label class="field check"><input v-model="editing.form.reduced_frame" type="checkbox" /><span>Reduced frame (*)</span></label>
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
