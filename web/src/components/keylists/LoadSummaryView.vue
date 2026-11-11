<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The Load List Summary Page: tables totalling up the Load List. Each table has a filter (which
// loads it looks at), hand-made rows (each a condition, e.g. everything fed from TX-1, and an
// optional reference load for <<Ref.field>>), and columns: Sum / Count / Min / Max / Average of a
// load field with an optional condition, or a formula over the row's other columns. Worked out
// from the Load List as it is, every time it is shown. Edit, try it (Preview), then Save.
import { computed, onMounted, ref } from 'vue';
import { ApiError, apiGet, apiPostJson, apiPostJsonForBlob, apiPut, exportToPath, runningInTauri } from '../../lib/engine';
import { newId } from '../../lib/refTypes';
import HistoryButton from '../audit/HistoryButton.vue';

type Check = { rule: string; message: string; severity: 'error' | 'warning' };
type Column = {
	id: string; name: string; kind: 'aggregate' | 'formula'; func: string; field: string; condition: string;
	applies_if: string; formula: string; otherwise: string; decimals: number | null; checks: Check[];
};
type Row = { id: string; name: string; condition: string; ref_tag: string };
type Table = { id: string; name: string; filter: string; columns: Column[]; rows: Row[]; total_row: boolean };
type Page = { tables: Table[] };
type Issue = { column: string; severity: 'error' | 'warning'; message: string };
type OutRow = { name: string; total: boolean; loads: number; tags: string[]; cells: (string | number | boolean | null)[]; issues: Issue[] };
type OutTable = { id: string; name: string; columns: string[]; rows: OutRow[]; issues: string[] };
type Choice = { key: string; label: string };
type View = { page: Page; tables: OutTable[]; fields: Choice[]; refs: Choice[]; funcs: Record<string, string> };

const API = '/api/load-summary';
const view = ref<View | null>(null);
const draft = ref<Page | null>(null);
const shown = ref<OutTable[]>([]);
const editing = ref(false);
const busy = ref(false);
const error = ref('');
const fields = ref<Record<string, string>>({});
const note = ref('');
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const dirty = computed(() => !!draft.value && !!view.value && JSON.stringify(draft.value) !== JSON.stringify(view.value.page));

async function call(fn: () => Promise<View>, keep = false) {
	busy.value = true;
	error.value = '';
	fields.value = {};
	try {
		const v = await fn();
		if (!keep) { view.value = v; draft.value = clone(v.page); }
		shown.value = v.tables;
		return v;
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
		if (err instanceof ApiError) fields.value = err.fields;
		return null;
	} finally {
		busy.value = false;
	}
}
onMounted(() => call(() => apiGet<View>(API)));
const preview = () => call(() => apiPostJson<View>(`${API}/preview`, draft.value), true);
async function save() {
	if (await call(() => apiPut<View>(API, draft.value))) { editing.value = false; note.value = 'Saved'; }
}
function discard() {
	if (!view.value) return;
	draft.value = clone(view.value.page);
	shown.value = view.value.tables;
	fields.value = {};
	editing.value = false;
}

async function exportXlsx() {
	note.value = '';
	const file = 'Load List Summary.xlsx';
	try {
		if (runningInTauri) {
			const { save: dialog } = await import('@tauri-apps/plugin-dialog');
			const path = await dialog({ defaultPath: file, filters: [{ name: 'Excel workbook', extensions: ['xlsx'] }] });
			if (path) note.value = `Saved ${(await exportToPath(`${API}/export`, {}, path)).path}`;
		} else {
			const href = URL.createObjectURL(await apiPostJsonForBlob(`${API}/export`, {}));
			Object.assign(document.createElement('a'), { href, download: file }).click();
			setTimeout(() => URL.revokeObjectURL(href), 10_000);
			note.value = `Downloaded ${file}`;
		}
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	}
}

// -- editing ---------------------------------------------------------------------------------
const err = (path: string) => fields.value[path] ?? '';
const blankColumn = (kind: Column['kind']): Column => ({ id: newId(), name: '', kind, func: 'sum', field: 'load_rating', condition: '',
	applies_if: '', formula: '', otherwise: '', decimals: null, checks: [] });
function addTable() {
	draft.value!.tables.push({ id: newId(), name: draft.value!.tables.length ? '' : 'Transformer loading', filter: 'not <<ispanel>>',
		columns: [{ ...blankColumn('aggregate'), name: 'Total kW' }, { ...blankColumn('aggregate'), name: 'Count', func: 'count' }],
		rows: [{ id: newId(), name: '', condition: "'TX-1' in <<supplychain>>", ref_tag: '' }], total_row: true });
}
function move<T>(list: T[], i: number, by: -1 | 1) {
	if (i + by >= 0 && i + by < list.length) [list[i], list[i + by]] = [list[i + by], list[i]];
}
/** Where "Insert" puts a reference: the box last typed in. */
let focused: { el: HTMLInputElement | HTMLTextAreaElement; set: (v: string) => void } | null = null;
function track(e: FocusEvent, set: (v: string) => void) {
	focused = { el: e.target as HTMLInputElement | HTMLTextAreaElement, set };
}
function insert(ref: string) {
	if (!ref || !focused) return;
	const { el, set } = focused;
	const at = el.selectionStart ?? el.value.length;
	set(el.value.slice(0, at) + ref + el.value.slice(el.selectionEnd ?? at));
	requestAnimationFrame(() => { el.focus(); el.setSelectionRange(at + ref.length, at + ref.length); });
}
const formulaRefs = (t: Table, self: Column) => [
	...t.columns.filter((c) => c.name.trim() && c.id !== self.id).map((c) => ({ ref: `<<${c.name.trim()}>>`, label: `the row's ${c.name.trim()}` })),
	{ ref: '<<Row>>', label: "the row's name" }, { ref: '<<Loads>>', label: 'how many loads the row has' },
	...(view.value?.refs ?? []).map((r) => ({ ref: `<<Ref.${r.key}>>`, label: `the reference load's ${r.label}` })),
];

const fmt = (v: unknown) => (v === null || v === undefined || v === '' ? '' : typeof v === 'number' ? (Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000)) : String(v));
const cellIssues = (r: OutRow, t: Table | undefined, c: number) => (t ? r.issues.filter((i) => i.column === t.columns[c]?.id) : []);
const tableOf = (id: string) => (editing.value ? draft.value : view.value?.page)?.tables.find((t) => t.id === id);
</script>

<template>
	<section class="card wizard ref-editor key-summary">
		<div class="mel-head">
			<span class="kind tree">Master list</span>
			<h2 class="key-title">Load List Summary Page</h2>
			<span class="hint small">Totals of the Load List, worked out now.</span>
			<span class="spacer" />
			<span v-if="dirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="note" class="saved" :title="note">✓ {{ note }}</span>
			<HistoryButton entity="load_summary" record-id="load-summary" label="Load List Summary Page" />
			<template v-if="!editing">
				<button type="button" class="secondary" :disabled="busy" @click="exportXlsx">Export .xlsx</button>
				<button type="button" class="secondary" :disabled="busy" title="Work it out again from the Load List" @click="call(() => apiGet<View>(API))">Refresh</button>
				<button type="button" :disabled="!view" @click="editing = true">Edit tables</button>
			</template>
			<template v-else>
				<button type="button" class="secondary" :disabled="busy" title="Work out the edited tables, without saving" @click="preview">▶ Preview</button>
				<button type="button" class="secondary" :disabled="busy" @click="discard">Discard</button>
				<button type="button" :disabled="busy || !dirty" @click="save">Save</button>
			</template>
		</div>
		<p v-if="error" class="error">{{ error }}</p>
		<p class="hint small">
			Each table looks at the active loads its <strong>filter</strong> lets in. A <strong>row</strong> takes those its condition holds for:
			<code>'TX-1' in &lt;&lt;supplychain&gt;&gt;</code> is every load fed from TX-1, directly or through the MCCs below it. A column
			totals a load field (Sum, Count, Min, Max, Average, each with an optional condition), or is a <strong>formula</strong> over the row's
			other columns, <code>&lt;&lt;Row&gt;&gt;</code>, <code>&lt;&lt;Loads&gt;&gt;</code> and the reference load's values
			(<code>&lt;&lt;Ref.load_rating&gt;&gt;</code>, e.g. a transformer's rating for its % loading).
		</p>

		<!-- the editor -->
		<div v-if="editing && draft" class="sum-edit">
			<section v-for="(t, ti) in draft.tables" :key="t.id" class="comp-table sum-table-edit">
				<div class="row tight comp-head">
					<label class="field"><span>Table</span><input v-model="t.name" placeholder="e.g. Transformer loading" :class="{ invalid: err(`${ti}.name`) }" /></label>
					<label class="field grow"><span>Filter <span class="hint small">which loads it looks at; blank: every active load</span></span>
						<input v-model="t.filter" class="mono" :class="{ invalid: err(`${ti}.filter`) }" @focus="track($event, (v) => (t.filter = v))" /></label>
					<label class="check"><input v-model="t.total_row" type="checkbox" /> Total row</label>
					<span class="spacer" />
					<button type="button" class="secondary small" :disabled="ti === 0" @click="move(draft.tables, ti, -1)">↑</button>
					<button type="button" class="secondary small" :disabled="ti === draft.tables.length - 1" @click="move(draft.tables, ti, 1)">↓</button>
					<button type="button" class="secondary small" :title="`Delete ${t.name || 'the table'}`" @click="draft.tables.splice(ti, 1)">✕</button>
				</div>
				<span v-for="k in [`${ti}.name`, `${ti}.filter`, `${ti}.columns`]" :key="k" class="warn small">{{ err(k) }}</span>

				<h4>Rows</h4>
				<table class="grid simple sum-rows">
					<thead><tr><th>Name</th><th>Condition <span class="hint small">which of the table's loads; blank: all</span></th><th>Reference load (tag)</th><th /></tr></thead>
					<tbody>
						<tr v-for="(r, ri) in t.rows" :key="r.id">
							<td><input v-model="r.name" :aria-label="`Row ${ri + 1} name`" :class="{ invalid: err(`${ti}.rows.${ri}.name`) }" :title="err(`${ti}.rows.${ri}.name`)" /></td>
							<td><input v-model="r.condition" class="mono" :aria-label="`Row ${ri + 1} condition`" :class="{ invalid: err(`${ti}.rows.${ri}.condition`) }"
								:title="err(`${ti}.rows.${ri}.condition`)" @focus="track($event, (v) => (r.condition = v))" /></td>
							<td><input v-model="r.ref_tag" placeholder="e.g. TX-1" :aria-label="`Row ${ri + 1} reference load`" /></td>
							<td class="actions">
								<button type="button" class="secondary small" :disabled="ri === 0" @click="move(t.rows, ri, -1)">↑</button>
								<button type="button" class="secondary small" :disabled="ri === t.rows.length - 1" @click="move(t.rows, ri, 1)">↓</button>
								<button type="button" class="secondary small" @click="t.rows.splice(ri, 1)">✕</button>
							</td>
						</tr>
					</tbody>
				</table>
				<p v-for="(r, ri) in t.rows" v-show="err(`${ti}.rows.${ri}.condition`)" :key="r.id" class="warn small">{{ r.name }}: {{ err(`${ti}.rows.${ri}.condition`) }}</p>
				<div class="row tight">
					<button type="button" class="secondary small" @click="t.rows.push({ id: newId(), name: '', condition: '', ref_tag: '' })">+ Row</button>
					<select aria-label="Insert a load reference" title="Put a reference to a load's value where you were typing (a filter or condition)"
						@change="insert(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
						<option value="">Insert a load reference…</option>
						<option v-for="x in view?.refs ?? []" :key="x.key" :value="`<<${x.key}>>`">&lt;&lt;{{ x.key }}&gt;&gt; – {{ x.label }}</option>
					</select>
				</div>

				<h4>Columns</h4>
				<div v-for="(c, ci) in t.columns" :key="c.id" class="sum-col">
					<div class="row tight">
						<input v-model="c.name" class="sum-col-name" placeholder="Column name" :aria-label="`Column ${ci + 1} name`" :class="{ invalid: err(`${ti}.columns.${ci}.name`) }" />
						<select v-model="c.kind" :aria-label="`Column ${ci + 1} kind`"><option value="aggregate">total of a field</option><option value="formula">formula</option></select>
						<template v-if="c.kind === 'aggregate'">
							<select v-model="c.func" :aria-label="`Column ${ci + 1} function`"><option v-for="(l, f) in view?.funcs ?? {}" :key="f" :value="f">{{ l }}</option></select>
							<select v-if="c.func !== 'count'" v-model="c.field" :aria-label="`Column ${ci + 1} field`" :class="{ invalid: err(`${ti}.columns.${ci}.field`) }">
								<option v-if="!view?.fields.some((f) => f.key === c.field)" :value="c.field">{{ c.field }}</option>
								<option v-for="f in view?.fields ?? []" :key="f.key" :value="f.key">{{ f.label }}</option>
							</select>
							<span class="hint small">of the loads where</span>
							<input v-model="c.condition" class="mono grow" placeholder="(all the row's loads)" :aria-label="`Column ${ci + 1} condition`"
								:class="{ invalid: err(`${ti}.columns.${ci}.condition`) }" @focus="track($event, (v) => (c.condition = v))" />
						</template>
						<template v-else>
							<input v-model="c.formula" class="mono grow" placeholder="e.g. <<Total kVA>> / <<Ref.load_rating>> * 100" :aria-label="`Column ${ci + 1} formula`"
								:class="{ invalid: err(`${ti}.columns.${ci}.formula`) }" @focus="track($event, (v) => (c.formula = v))" />
						</template>
						<label class="check small" title="Round a number to this many decimals">dp
							<input type="number" min="0" max="10" class="sum-dp" :value="c.decimals ?? ''" :aria-label="`Column ${ci + 1} decimals`"
								@input="c.decimals = ($event.target as HTMLInputElement).value === '' ? null : Number(($event.target as HTMLInputElement).value)" /></label>
						<button type="button" class="secondary small" :disabled="ci === 0" @click="move(t.columns, ci, -1)">↑</button>
						<button type="button" class="secondary small" :disabled="ci === t.columns.length - 1" @click="move(t.columns, ci, 1)">↓</button>
						<button type="button" class="secondary small" @click="t.columns.splice(ci, 1)">✕</button>
					</div>
					<div v-if="c.kind === 'formula'" class="row tight sum-col-more">
						<span class="hint small">Applies when</span>
						<input v-model="c.applies_if" class="mono" placeholder="(always)" :aria-label="`Column ${ci + 1} applies when`" @focus="track($event, (v) => (c.applies_if = v))" />
						<span class="hint small">otherwise</span>
						<input v-model="c.otherwise" class="mono" placeholder="(blank)" :aria-label="`Column ${ci + 1} otherwise`" @focus="track($event, (v) => (c.otherwise = v))" />
						<select aria-label="Insert a reference" @change="insert(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
							<option value="">Insert…</option>
							<option v-for="x in formulaRefs(t, c)" :key="x.ref" :value="x.ref">{{ x.ref }} – {{ x.label }}</option>
						</select>
					</div>
					<div class="row tight sum-col-more">
						<span class="hint small">Checks:</span>
						<span v-for="(ch, n) in c.checks" :key="n" class="row tight sum-check">
							<input v-model="ch.rule" class="mono" placeholder="e.g. <<value>> < 80" :aria-label="`Column ${ci + 1} check ${n + 1}`" @focus="track($event, (v) => (ch.rule = v))" />
							<input v-model="ch.message" placeholder="Message" :aria-label="`Column ${ci + 1} check ${n + 1} message`" />
							<select v-model="ch.severity"><option value="error">error</option><option value="warning">warning</option></select>
							<button type="button" class="secondary small" @click="c.checks.splice(n, 1)">✕</button>
						</span>
						<button type="button" class="secondary small" @click="c.checks.push({ rule: '', message: '', severity: 'warning' })">+ Check</button>
					</div>
					<template v-for="part in ['name', 'field', 'condition', 'formula', 'applies_if', 'otherwise', 'checks.0', 'checks.1', 'checks.2']" :key="part">
						<span v-if="err(`${ti}.columns.${ci}.${part}`)" class="warn small">{{ c.name }}: {{ err(`${ti}.columns.${ci}.${part}`) }}</span>
					</template>
				</div>
				<div class="row tight">
					<button type="button" class="secondary small" @click="t.columns.push(blankColumn('aggregate'))">+ Total column</button>
					<button type="button" class="secondary small" @click="t.columns.push(blankColumn('formula'))">+ Formula column</button>
				</div>
			</section>
			<button type="button" class="secondary" @click="addTable">+ Table</button>
		</div>

		<!-- the tables, worked out -->
		<p v-if="view && !shown.length && !editing" class="hint">No summary tables yet. Use <strong>Edit tables</strong> to add one.</p>
		<section v-for="t in shown" :key="t.id" class="sum-out">
			<h3>{{ t.name }} <span v-if="editing" class="hint small">(preview)</span></h3>
			<p v-for="i in t.issues" :key="i" class="warn small">⚠ {{ i }}</p>
			<table class="grid simple">
				<thead><tr><th>Row</th><th v-for="c in t.columns" :key="c">{{ c }}</th><th class="hint">Loads</th></tr></thead>
				<tbody>
					<tr v-for="r in t.rows" :key="r.name" :class="{ 'sum-total': r.total }">
						<td :title="r.issues.filter((i) => !i.column).map((i) => `${i.severity}: ${i.message}`).join('\n')">
							{{ r.name }}<span v-if="r.issues.some((i) => !i.column)" class="calc-warning"> ⚠</span></td>
						<td v-for="(v, ci) in r.cells" :key="ci" class="num">
							<span v-if="cellIssues(r, tableOf(t.id), ci).length" :class="cellIssues(r, tableOf(t.id), ci).some((i) => i.severity === 'error') ? 'calc-error' : 'calc-warning'"
								:title="cellIssues(r, tableOf(t.id), ci).map((i) => `${i.severity}: ${i.message}`).join('\n')">
								{{ cellIssues(r, tableOf(t.id), ci).some((i) => i.severity === 'error') ? '⛔' : '⚠' }} {{ fmt(v) }}</span>
							<template v-else>{{ fmt(v) }}</template>
						</td>
						<td class="num hint" :title="r.tags.join(', ')">{{ r.loads }}</td>
					</tr>
				</tbody>
			</table>
		</section>
	</section>
</template>
