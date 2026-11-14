<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// A load type's component tables: for each, the parts (circuit breaker, contactor…) for each
// range of a load's rating or another of its fields. A load gets the first row whose
// Min <= its value <= Max (blank: open-ended); template rows reach it as
// <<LoadType.CB.PartNumber>>. Edits go straight into `tables` (saved with the load type).
import { onMounted, ref } from 'vue';
import { apiGet } from '../../lib/engine';
import type { ComponentTable } from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import EditGrid, { type CellEdit, type GridColumn } from '../common/EditGrid.vue';
import { useUndo } from '../../lib/history';

const props = defineProps<{ tables: ComponentTable[]; errors: Record<string, string>; formId: string }>();
// Undo for the tables' grids (one history for all of them); it starts again when another record's tables are shown.
const hist = useUndo({ get: () => props.tables, resetOn: () => props.tables });
// What a table can be matched on: the Load List's fields (calculated ones too), then what the app works out.
const choices = ref<{ key: string; label: string }[]>([]);
const APP = [{ key: 'rating', label: 'Rating (the load rating)' }, { key: 'voltage', label: "Voltage (the load's, else the load type's)" },
	{ key: 'qty', label: 'Quantity' }, { key: 'cable_length', label: 'Cable length (m)' }, { key: 'cable_size', label: 'Cable size (mm²)' }];
onMounted(async () => {
	try {
		const v = await apiGet<{ fields: { key: string; label: string; kind: string }[] }>('/api/load-fields');
		choices.value = [...v.fields.filter((f) => f.kind !== 'text' && f.kind !== 'yes/no' || f.key === 'load_rating')
			.map((f) => ({ key: f.key, label: `${f.label}${f.kind === 'calc' ? ' (calculated)' : ''}` })), ...APP];
	} catch { choices.value = [{ key: 'load_rating', label: 'Load rating' }, ...APP]; }
});
const err = (i: number, part: string) => props.errors[`${props.formId}.components.${i}.${part}`] ?? '';
const rowErrors = (i: number) => Object.entries(props.errors).filter(([k]) => k.startsWith(`${props.formId}.components.${i}.rows`)).map(([, m]) => m);
const tagName = (s: string) => s.replace(/\s+/g, '');

function add() {
	props.tables.push({ id: newId(), name: props.tables.length ? '' : 'CB', match_field: 'load_rating', columns: ['Part Number', 'Manufacturer', 'Description'],
		rows: [{ min: '0', max: '', values: {} }] });
}
function move(i: number, by: -1 | 1) {
	const t = props.tables;
	if (i + by >= 0 && i + by < t.length) [t[i], t[i + by]] = [t[i + by], t[i]];
}
function renameColumn(t: ComponentTable, c: number, name: string) {
	const was = t.columns[c];
	t.columns[c] = name;
	for (const r of t.rows) if (was in r.values) { r.values[name] = r.values[was]; delete r.values[was]; }
}
function removeColumn(t: ComponentTable, c: number) {
	const [was] = t.columns.splice(c, 1);
	for (const r of t.rows) delete r.values[was];
}

const gridCols = (t: ComponentTable): GridColumn[] => [
	{ label: 'Min', width: 80, title: 'The range starts at (blank: no lower limit)' },
	{ label: 'Max', width: 80, title: 'The range ends at, inclusive (blank: no upper limit)' },
	...t.columns.map((c): GridColumn => ({ label: c, width: /Description/i.test(c) ? 220 : 140 })),
];
const gridCells = (t: ComponentTable) => t.rows.map((r) => [r.min ?? '', r.max ?? '', ...t.columns.map((c) => r.values[c] ?? '')]);
function setCells(t: ComponentTable, edits: CellEdit[]) {
	for (const e of edits) {
		const r = t.rows[e.r];
		if (!r) continue;
		const v = e.value.trim();
		if (e.c === 0) r.min = v || null;
		else if (e.c === 1) r.max = v || null;
		else if (t.columns[e.c - 2]) {
			if (v) r.values[t.columns[e.c - 2]] = v;
			else delete r.values[t.columns[e.c - 2]];
		}
	}
}
const insertRows = (t: ComponentTable, at: number, n: number) => t.rows.splice(at, 0, ...Array.from({ length: n }, () => ({ min: null, max: null, values: {} })));
function removeRows(t: ComponentTable, idx: number[]) {
	const drop = new Set(idx);
	t.rows = t.rows.filter((_, i) => !drop.has(i));
}
</script>

<template>
	<div class="comp-tables">
		<p class="hint small">
			Parts that depend on the load: a table per kind of component (a circuit breaker, a contactor…), with a row for each range of a
			load's field. A load gets the first row whose <strong>Min ≤ its value ≤ Max</strong> (a blank Min or Max is open-ended).
			Its rows reach it as <code>&lt;&lt;LoadType.CB.PartNumber&gt;&gt;</code> (the table, then a column; spaces in names can be left out).
			A load with no value there, or one no row fits, gets blank: <code>|default:TBA</code> fills it.
		</p>
		<section v-for="(t, i) in tables" :key="t.id" class="comp-table">
			<div class="row tight comp-head">
				<label class="field"><span>Table</span>
					<input v-model="t.name" placeholder="e.g. CB" maxlength="25" :aria-label="`Table ${i + 1} name`" :class="{ invalid: err(i, 'name') }" /></label>
				<label class="field"><span>Matched on</span>
					<select v-model="t.match_field" :aria-label="`Table ${i + 1} matched on`">
						<option v-if="!choices.some((c) => c.key === t.match_field)" :value="t.match_field">{{ t.match_field }}</option>
						<option v-for="c in choices" :key="c.key" :value="c.key">{{ c.label }}</option>
					</select></label>
				<code v-if="t.name.trim()" class="hint small comp-tag">&lt;&lt;LoadType.{{ tagName(t.name) }}.{{ tagName(t.columns[0] ?? 'Column') }}&gt;&gt;</code>
				<span class="spacer" />
				<button type="button" class="secondary small" :disabled="i === 0" title="Move up" @click="move(i, -1)">↑</button>
				<button type="button" class="secondary small" :disabled="i === tables.length - 1" title="Move down" @click="move(i, 1)">↓</button>
				<button type="button" class="secondary small" :title="`Delete the ${t.name || 'table'} table`" @click="tables.splice(i, 1)">✕</button>
			</div>
			<span v-if="err(i, 'name')" class="warn small">{{ err(i, 'name') }}</span>
			<div class="row tight comp-cols">
				<span class="hint small">Columns:</span>
				<span v-for="(c, n) in t.columns" :key="n" class="comp-col">
					<input :value="c" :aria-label="`Table ${i + 1} column ${n + 1}`" @change="renameColumn(t, n, ($event.target as HTMLInputElement).value.trim())" />
					<button type="button" class="secondary small" :title="`Remove the ${c} column`" @click="removeColumn(t, n)">✕</button>
				</span>
				<button type="button" class="secondary small" @click="t.columns.push(`Column ${t.columns.length + 1}`)">+ Column</button>
			</div>
			<span v-if="err(i, 'columns')" class="warn small">{{ err(i, 'columns') }}</span>
			<EditGrid :columns="gridCols(t)" :cells="gridCells(t)" :history="hist" :height="Math.min(300, 96 + 26 * Math.max(3, t.rows.length))"
				@set="(e) => setCells(t, e)" @insert="(at, n) => insertRows(t, at, n)" @remove="(idx) => removeRows(t, idx)" />
			<p v-for="m in rowErrors(i)" :key="m" class="warn small">{{ m }}</p>
		</section>
		<button type="button" class="secondary small" @click="add">+ Component table</button>
	</div>
</template>
