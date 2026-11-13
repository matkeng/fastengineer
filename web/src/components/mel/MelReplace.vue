<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Find Replace: a new column made from a column of the table, with whole values replaced. The
// table is the one after Custom rows; the values of the chosen column are listed once each,
// sorted, with a box for what replaces each. An empty box keeps the value; "Blank" empties it.
import { computed, ref } from 'vue';
import type { FindReplace } from '../../lib/melTypes';
import { useStage } from '../../lib/useStage';
import { useMel } from '../../stores/mel';

const MAX = 100;
const mel = useMel();
const { result } = useStage('custom', (r) => [r.columns, r.hidden_rows, r.text_columns, r.overrides, r.custom_rows]);
const list = computed(() => mel.draft!.find_replace);
const selected = ref<number | null>(list.value.length ? 0 : null);
const filter = ref('');
const fr = computed<FindReplace | null>(() => (selected.value === null ? null : list.value[selected.value] ?? null));

// Columns a find/replace can read: the table's, and the find/replace columns before it.
const columns = computed(() => [...(result.value?.headers ?? []), ...list.value.slice(0, selected.value ?? 0).map((f) => f.name.trim()).filter(Boolean)]);
const taken = computed(() => new Set(result.value?.headers ?? []));

function add() {
	let n = 1;
	while (taken.value.has(`New column ${n}`) || list.value.some((f) => f.name === `New column ${n}`)) n++;
	list.value.push({ name: `New column ${n}`, column: '', replacements: [] });
	selected.value = list.value.length - 1;
	filter.value = '';
}
function remove(i: number) {
	if (!confirm(`Delete the find/replace column "${list.value[i].name}"?`)) return;
	list.value.splice(i, 1);
	selected.value = list.value.length ? Math.min(i, list.value.length - 1) : null;
}
function move(i: number, d: -1 | 1) {
	const j = i + d;
	if (j < 0 || j >= list.value.length) return;
	[list.value[i], list.value[j]] = [list.value[j], list.value[i]];
	if (selected.value === i) selected.value = j;
}
function problem(i: number): string | null {
	const f = list.value[i];
	const name = f.name.trim();
	if (!name) return 'Needs a name';
	if (taken.value.has(name)) return 'A column with this name already exists';
	if (list.value.some((x, j) => j < i && x.name.trim() === name)) return 'Duplicate name';
	if (!f.column) return 'Choose the column to read';
	return null;
}

// The chosen column's values, each once, sorted (numbers in order), with how many rows have it.
// A find/replace column's values are worked out here from the one it reads, as the engine does.
function valuesOf(column: string, upTo: number): Map<string, number> {
	const rows = result.value?.rows ?? [];
	const chain: FindReplace[] = [];
	let col = column;
	for (let j = upTo - 1; j >= 0; j--) {
		if (list.value[j].name.trim() === col) {
			chain.unshift(list.value[j]);
			col = list.value[j].column;
		}
	}
	const counts = new Map<string, number>();
	for (const r of rows) {
		let v = r.values[col] ?? '';
		for (const c of chain) {
			const hit = c.replacements.find((x) => x.find === v);
			if (hit) v = hit.replace;
		}
		counts.set(v, (counts.get(v) ?? 0) + 1);
	}
	return counts;
}
const values = computed(() => {
	const f = fr.value;
	if (!f || !f.column) return { all: 0, shown: [] as [string, number][], hidden: 0 };
	const counts = valuesOf(f.column, selected.value ?? 0);
	const q = filter.value.trim().toLowerCase();
	const sorted = [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true, sensitivity: 'base' }));
	const matching = q ? sorted.filter(([v]) => v.toLowerCase().includes(q)) : sorted;
	return { all: counts.size, shown: matching.slice(0, MAX), hidden: Math.max(0, matching.length - MAX) };
});
// Replacements whose value is no longer in the column (kept, in case it comes back in a later file).
const stale = computed(() => {
	const f = fr.value;
	if (!f || !f.column) return [];
	const counts = valuesOf(f.column, selected.value ?? 0);
	return f.replacements.filter((r) => !counts.has(r.find));
});

const entry = (v: string) => fr.value?.replacements.find((r) => r.find === v);
function textOf(v: string): string {
	const e = entry(v);
	return e && e.replace !== '' ? e.replace : '';
}
function setText(v: string, text: string) {
	const f = fr.value!;
	const i = f.replacements.findIndex((r) => r.find === v);
	if (text === '') {
		if (i >= 0) f.replacements.splice(i, 1); // no change
	} else if (i >= 0) f.replacements[i].replace = text;
	else f.replacements.push({ find: v, replace: text });
}
const isBlank = (v: string) => entry(v)?.replace === '';
function setBlank(v: string, on: boolean) {
	const f = fr.value!;
	const i = f.replacements.findIndex((r) => r.find === v);
	if (on) {
		if (i >= 0) f.replacements[i].replace = '';
		else f.replacements.push({ find: v, replace: '' });
	} else if (i >= 0) f.replacements.splice(i, 1);
}
function chooseColumn(e: Event) {
	const f = fr.value!;
	const col = (e.target as HTMLSelectElement).value;
	if (f.replacements.length && !confirm(`Read ${col} instead of ${f.column}? Its ${f.replacements.length} replacement(s) are kept where the values match.`)) {
		(e.target as HTMLSelectElement).value = f.column;
		return;
	}
	f.column = col;
	filter.value = '';
}
const show = (v: string) => (v === '' ? '(blank)' : v);
</script>

<template>
	<div class="mel-replace">
		<p class="hint">
			Make a new column from a column of the table, replacing <strong>whole values</strong>: choose the column, name the new one, then type what
			replaces each value. An empty box keeps the value as it is; tick <strong>Blank</strong> to empty it. The column you read is not changed,
			and Calculated columns and Mapping can use the new one. Rows added in Custom rows are included.
		</p>
		<div class="replace-layout">
			<div class="replace-list">
				<table v-if="list.length" class="grid simple">
					<thead><tr><th>New column</th><th>From</th><th /></tr></thead>
					<tbody>
						<tr v-for="(f, i) in list" :key="i" :class="{ selected: selected === i }" @click="selected = i; filter = ''">
							<td>{{ f.name || '(no name)' }}<div v-if="problem(i)" class="warn small">{{ problem(i) }}</div></td>
							<td>{{ f.column || '—' }} <span class="hint small">{{ f.replacements.length }} replaced</span></td>
							<td class="actions">
								<button type="button" class="secondary small" :disabled="i === 0" title="Move up" @click.stop="move(i, -1)">↑</button>
								<button type="button" class="secondary small" :disabled="i === list.length - 1" title="Move down" @click.stop="move(i, 1)">↓</button>
								<button type="button" class="secondary small" @click.stop="remove(i)">Delete</button>
							</td>
						</tr>
					</tbody>
				</table>
				<button type="button" @click="add">Add find/replace column</button>
			</div>

			<div v-if="fr" class="replace-editor">
				<div class="form-grid two-col">
					<label class="field"><span>Column to read</span>
						<select :value="fr.column" data-test="fr-column" @change="chooseColumn">
							<option value="" disabled>— choose a column —</option>
							<option v-for="c in columns" :key="c" :value="c">{{ c }}</option>
						</select>
					</label>
					<label class="field"><span>New column name</span>
						<input v-model="fr.name" data-test="fr-name" :class="{ invalid: problem(selected!) && fr.name.trim() !== '' && taken.has(fr.name.trim()) }" />
					</label>
				</div>
				<template v-if="fr.column">
					<div class="row">
						<span class="hint small">
							{{ values.all }} different value(s) in {{ fr.column }}<template v-if="values.hidden">; showing the first {{ MAX }}<template v-if="filter"> that match</template>, filter to find others</template>.
						</span>
						<span class="spacer" />
						<input v-model="filter" type="search" placeholder="Filter values…" aria-label="Filter values" />
					</div>
					<table class="grid simple replace-values">
						<thead><tr><th>Value in {{ fr.column }}</th><th class="num">Rows</th><th>Replace with</th><th>Blank</th></tr></thead>
						<tbody>
							<tr v-for="[v, n] in values.shown" :key="v" :class="{ changed: !!entry(v) }">
								<td :class="{ hint: v === '' }">{{ show(v) }}</td>
								<td class="num">{{ n }}</td>
								<td><input :value="textOf(v)" :disabled="isBlank(v)" :placeholder="isBlank(v) ? '(made blank)' : 'no change'"
									:aria-label="`Replace ${show(v)} with`" @input="setText(v, ($event.target as HTMLInputElement).value)" /></td>
								<td class="center"><input type="checkbox" :checked="isBlank(v)" :aria-label="`Make ${show(v)} blank`" @change="setBlank(v, ($event.target as HTMLInputElement).checked)" /></td>
							</tr>
							<tr v-if="!values.shown.length"><td colspan="4" class="hint">No values{{ filter ? ' match the filter' : '' }}.</td></tr>
						</tbody>
					</table>
					<div v-if="stale.length" class="stale">
						<p class="hint small">Replacements of values that are not in {{ fr.column }} now (kept, in case they come back in a later file):</p>
						<ul>
							<li v-for="r in stale" :key="r.find">
								{{ show(r.find) }} → {{ r.replace === '' ? '(blank)' : r.replace }}
								<button type="button" class="link small" @click="setText(r.find, ''); setBlank(r.find, false)">Remove</button>
							</li>
						</ul>
					</div>
				</template>
			</div>
		</div>
	</div>
</template>

<style scoped>
.replace-layout { display: grid; grid-template-columns: minmax(260px, 1fr) 2fr; gap: 1rem; align-items: start; }
.replace-list tr { cursor: pointer; }
.replace-list tr.selected td { background: var(--selected, #e8f0fe); }
.replace-values td { vertical-align: middle; }
.replace-values td input:not([type=checkbox]) { width: 100%; }
.replace-values tr.changed td:first-child { font-weight: 600; }
.replace-values .num { text-align: right; width: 4em; }
.replace-values .center { text-align: center; width: 4em; }
.stale ul { margin: 0.25rem 0 0 1rem; }
@media (max-width: 900px) { .replace-layout { grid-template-columns: 1fr; } }
</style>
