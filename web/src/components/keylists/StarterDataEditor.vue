<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Starter Coordination: Type 2 coordinated DOL starter selections by motor kW (a project starts
// with NHP's six charts: 50 kA and 65 kA, CEP7 or E300 overloads). A grid of every row,
// filterable by chart; a row is added or edited in a form. Each load type names the chart its
// loads use (blank: the project's default chart, set here); a load gets the chart's row for the
// smallest motor at least its kW, reached as <<Starter.CB>>, <<Starter.Contactor>>…
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

type Starter = Record<string, string | number | boolean | null> & { id: string; chart: string; kw: number };
type StarterList = { items: Starter[]; default_chart: string };
const API = '/api/keylists/starters';
const kl = useKeyLists();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<Starter> | null = null;
const items = ref<Starter[] | null>(null);
const busy = ref(false);
const error = ref('');
const note = ref('');

// field, title, tag (<<Starter.Tag>>), select filter
const COLS: { field: string; title: string; tag?: string; select?: boolean; text?: boolean }[] = [
	{ field: 'chart', title: 'Chart', tag: 'Chart', select: true, text: true }, { field: 'fault_ka', title: 'Fault kA', tag: 'FaultkA', select: true },
	{ field: 'manufacturer', title: 'Make', select: true, text: true }, { field: 'kw', title: 'Motor kW', tag: 'kW' },
	{ field: 'flc', title: 'FLC @ 400V', tag: 'FLC' }, { field: 'cb', title: 'Circuit breaker', tag: 'CB', text: true },
	{ field: 'cb_amps', title: 'CB Amps', tag: 'CBAmps' }, { field: 'el_setting', title: 'Earth leakage', tag: 'ELSetting', text: true },
	{ field: 'contactor', title: 'Contactor', tag: 'Contactor', select: true, text: true }, { field: 'overload', title: 'Overload relay', tag: 'Overload', text: true },
	{ field: 'range_min', title: 'Setting from (A)', tag: 'RangeMin' }, { field: 'range_max', title: 'Setting to (A)', tag: 'RangeMax' },
	{ field: 'inst_trip', title: 'C/B inst. trip (A)', tag: 'InstTrip' }, { field: 'min_trip', title: 'Min trip × FLC', tag: 'MinTrip' },
	{ field: 'note', title: 'Note', tag: 'Note', text: true },
];
const HIDDEN = new Set(['manufacturer', 'cb_amps']);
const NOTES: Record<string, string> = { '*': 'Overload mounted separately from the contactor, or use the pass-thru version',
	'^': '75 kW and above: kit with separate 5P10-5A CTs and a 193-1EF*Z overload' };
const defaultChart = ref('');
const charts = computed(() => [...new Set((items.value ?? []).map((r) => r.chart).filter(Boolean))]);
const distinct = (f: string) => [...new Set((items.value ?? []).map((r) => String(r[f] ?? '')).filter(Boolean))]
	.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

async function load() {
	try {
		const got = await apiGet<StarterList>(API);
		items.value = got.items;
		defaultChart.value = got.default_chart;
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	}
}
onMounted(load);
// a workbook import or reset (ListWorkbook) refreshes the project's overview: read the list again
watch(() => kl.overview?.starters, () => { if (!busy.value) void load(); });

function build() {
	if (!host.value || !items.value) return;
	table?.api.destroy();
	const columns = COLS.map((c): ColumnsConfig => ({
		title: escapeHtml(c.title),
		data: (r: Starter) => r[c.field] ?? null,
		visible: !HIDDEN.has(c.field), // shown with Columns
		className: c.text ? (c.field === 'chart' ? 'key-col' : '') : 'dt-right',
		render: (v: string | number | null, type: string, r: Starter) => {
			if (v === null || v === '') return '';
			if (type === 'sort' || type === 'type') return typeof v === 'number' ? v : String(v).toLowerCase();
			const text = escapeHtml(String(v));
			return c.field === 'note' && NOTES[String(v)] ? `<span title="${escapeHtml(NOTES[String(v)])}">${text}</span>` : text;
		},
	}));
	const selects: Record<number, SelectFilter<Starter>> = {};
	COLS.forEach((c, i) => {
		if (!c.select) return;
		selects[i] = { options: [{ value: '', label: 'All' }, ...distinct(c.field).map((v) => ({ value: v, label: v }))], test: (v, r) => v === '' || String(r[c.field]) === v };
	});
	table = createFilteredTable<Starter>(host.value, columns.length, {
		data: items.value, columns, order: [] /* the list's own order: chart by chart, by kW */, pageLength: 50, lengthMenu: [25, 50, 100, 250],
		layout: TOOLBAR_LAYOUT,
		buttons: [{ extend: 'colvis', text: 'Columns' }, { extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: 'Starter Coordination' }],
		language: { search: 'Search all:', emptyTable: 'No rows. Use "Add row" or "Add missing NHP charts".' },
	}, selects);
}
watch([host, items], build);
onBeforeUnmount(() => table?.api.destroy());

// -- the form ---------------------------------------------------------------------------
const editing = ref<{ isNew: boolean; form: Record<string, string | boolean> } | null>(null);
const formErrors = ref<Record<string, string>>({});
function open(row: Starter | null) {
	formErrors.value = {};
	error.value = '';
	const form: Record<string, string | boolean> = { id: row?.id ?? newId() };
	for (const c of COLS) form[c.field] = row ? String(row[c.field] ?? '') : '';
	if (!row) Object.assign(form, { chart: defaultChart.value, manufacturer: 'NHP' });
	editing.value = { isNew: !row, form };
}
function onClick(e: MouseEvent) {
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as Starter | undefined;
	if (row) open(row);
}
async function put(list: unknown[], id?: string, chart = defaultChart.value) {
	busy.value = true;
	error.value = '';
	try {
		const got = await apiPut<StarterList>(API, { items: list, default_chart: chart });
		items.value = got.items;
		defaultChart.value = got.default_chart;
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
	const i = list.findIndex((r) => (r as Starter).id === e.form.id);
	if (i >= 0) list.splice(i, 1, e.form);
	else list.push(e.form);
	if (await put(list, String(e.form.id))) { editing.value = null; note.value = 'Saved'; }
}
async function remove() {
	const e = editing.value;
	if (!e || e.isNew || !items.value || !confirm(`Delete the ${e.form.chart} ${e.form.kw} kW row?`)) return;
	if (await put(items.value.filter((r) => r.id !== e.form.id))) editing.value = null;
}
async function addDefaults() {
	busy.value = true;
	try {
		const before = items.value?.length ?? 0;
		const got = await apiPostJson<StarterList>(`${API}/defaults`, {});
		items.value = got.items;
		defaultChart.value = got.default_chart;
		note.value = items.value.length > before ? `Added ${items.value.length - before} NHP row(s)` : 'Every NHP chart row is already in the list';
		await kl.refresh();
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	} finally {
		busy.value = false;
	}
}
const count = computed(() => items.value?.length ?? 0);
async function setDefault(e: Event) {
	const chart = (e.target as HTMLSelectElement).value;
	if (!items.value) return;
	if (await put([...items.value], undefined, chart)) note.value = `Default chart: ${chart}`;
	else (e.target as HTMLSelectElement).value = defaultChart.value;
}
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-codes key-starters">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Starter Coordination</h2>
			<span class="hint small">{{ count }} row(s) in {{ charts.length }} chart(s). Click a row to edit or delete it.</span>
			<span class="spacer" />
			<span v-if="note" class="saved">✓ {{ note }}</span>
			<label class="inline small" title="The chart of load types that don't name one (Load Types: Starter chart)">Project default chart
				<select :value="defaultChart" :disabled="busy" data-test="default-chart" @change="setDefault">
					<option v-for="c in charts" :key="c" :value="c">{{ c }}</option>
				</select>
			</label>
			<button type="button" class="secondary" :disabled="busy" title="Add back any rows of NHP's six Type 2 charts that are not in the list; nothing else changes" @click="addDefaults">Add missing NHP charts</button>
			<HistoryButton entity="starters" record-id="starters" label="Starter Coordination" />
			<ListWorkbook list-id="starters" name="Starter Coordination" />
			<button type="button" @click="open(null)">Add row</button>
		</div>
		<p v-if="error && !editing" class="error">{{ error }}</p>
		<p class="hint small">
			Starts with <strong>NHP's Type 2 coordination charts</strong> for DOL starters at 400/415 V (Terasaki ZS earth leakage circuit breakers,
			AS/NZS 60947.4.1): <strong>50 kA</strong> ECH54.2, ECH54.12, RECH54.23 and <strong>65 kA</strong> ECH64.2, ECH64.13, RECH64.24, with
			Sprecher+Schuh CA7/CA9 or Allen-Bradley 100-C contactors and CEP7-1EF or E300 overloads. Each load type names its <strong>Starter chart</strong>
			(blank: the project default above; <em>None</em>: no starter). A load gets the chart's row for the smallest motor at least its kW (Hp converted;
			a rating in Amps on the FLC), and its rows reach it as <code>&lt;&lt;Starter.CB&gt;&gt;</code>, <code>&lt;&lt;Starter.Contactor&gt;&gt;</code>,
			<code>&lt;&lt;Starter.Overload&gt;&gt;</code>, <code>&lt;&lt;Starter.Range&gt;&gt;</code>, <code>&lt;&lt;Starter.InstTrip&gt;&gt;</code>…
			Set the circuit breaker Ir to 1 (= In) and the overload to the motor FLC. Notes: <code>*</code> {{ NOTES['*'] }}; <code>^</code> {{ NOTES['^'] }}.
		</p>
		<div class="results mel-grid">
			<div ref="host" class="result-table ref-rows" @click="onClick" />
		</div>

		<AppModal :open="!!editing" :title="editing?.isNew ? 'Add starter row' : `${editing?.form.chart} ${editing?.form.kw} kW`" @close="editing = null">
			<form v-if="editing" class="form-grid two-col motor-form drive-form" @submit.prevent="save">
				<label v-for="c in COLS" :key="c.field" class="field">
					<span>{{ c.title }}<span v-if="['chart', 'kw'].includes(c.field)" class="req"> *</span>
						<code v-if="c.tag" class="hint small">&lt;&lt;Starter.{{ c.tag }}&gt;&gt;</code></span>
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
