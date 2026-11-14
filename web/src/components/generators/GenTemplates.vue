<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Template blocks: one block per template ID; each row becomes an output row for every run
// that picks it. Text cells hold <<TAG>> placeholders; calculated columns are set per generator.
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import {
	type Computed, type PreviewResult, type Scalar, type TemplateCell, asTyped, cellText, isTag,
} from '../../lib/genTypes';
import { useGenerators } from '../../stores/generators';
import EditGrid, { type CellEdit, type GridColumn } from '../common/EditGrid.vue';
import { useUndo } from '../../lib/history';

const g = useGenerators();
const gen = computed(() => g.draft!.generator);
// Undo for the grid: back to the templates as they were before each edit, until they are saved or loaded again.
const hist = useUndo({ get: () => g.draft?.generator.templates, resetOn: () => g.saved });
const filter = ref('');
const lower = (s: string | null | undefined) => (s ?? '').trim().toLowerCase();

// First block of each ID (the one the build uses), plus how many further blocks repeat it
const blocks = computed(() => {
	const seen = new Map<string, { id: string; index: number; rows: number; dups: number }>();
	gen.value.templates.forEach((t, index) => {
		const b = seen.get(t.id);
		if (b) b.dups += 1;
		else seen.set(t.id, { id: t.id, index, rows: t.rows.length, dups: t.duplicate_blocks });
	});
	return [...seen.values()];
});
const usage = computed(() => Object.fromEntries((g.checkResult?.template_index ?? []).map((e) => [e.id, e.runs])));
const shown = computed(() => {
	const q = filter.value.trim().toLowerCase();
	return q ? blocks.value.filter((b) => b.id.toLowerCase().includes(q) || descOf(b.index).toLowerCase().includes(q)) : blocks.value;
});
const current = computed(() => {
	const b = blocks.value.find((x) => x.id === g.selectedTemplate) ?? blocks.value[0];
	return b ? gen.value.templates[b.index] : null;
});
const descCol = computed(() => gen.value.output_columns.findIndex((c) => /^desc/i.test(c.name)));
function descOf(index: number): string {
	const t = gen.value.templates[index];
	const c = descCol.value >= 0 ? t?.rows[0]?.cells[descCol.value] : undefined;
	return c ? cellText(c.text ?? c.value) : '';
}

// -- grid --------------------------------------------------------------------------

const computedCol = (i: number) => gen.value.output_columns[i]?.computed ?? null;
const describe = (c: Computed | null) => {
	if (!c) return 'calculated';
	if (c.kind === 'concat') return 'join: ' + (c.parts as (string | { col: string })[]).map((p) => (typeof p === 'string' ? `"${p}"` : `[${p.col}]`)).join(' & ');
	if (c.kind === 'lookup') return `look up [${c.key}] in ${c.table} ${c.key_column} → ${c.return_column}`;
	if (c.kind === 'exists') return `[${c.value}] exists in ${c.table} ${c.column}`;
	if (c.kind === 'count') return `count of [${c.equals}] in ${c.table} ${c.column}`;
	return String(c.expression ?? 'expression');
};
const columns = computed<GridColumn[]>(() => gen.value.output_columns.map((c, i) => {
	const calc = !!c.computed || !!current.value?.rows.some((r) => r.cells[i]?.kind === 'computed');
	return {
		label: c.name || `#${i + 1}`,
		readonly: calc,
		badge: calc ? 'calc' : c.raw ? 'key' : undefined,
		title: calc ? describe(c.computed ?? current.value?.rows.find((r) => r.cells[i]?.override)?.cells[i].override ?? null)
			: c.raw ? 'Lookup key, written without expanding tags' : c.name,
		width: /seq|run/i.test(c.name) ? 70 : 160,
	};
}));
function cellShown(c: TemplateCell | undefined, i: number): string {
	if (!c) return '';
	if (c.kind === 'computed') return `ƒ ${(c.override ?? computedCol(i))?.kind ?? 'calc'}`;
	return c.text ?? cellText(c.value);
}
const cells = computed(() => (current.value?.rows ?? []).map((r) => gen.value.output_columns.map((_, i) => cellShown(r.cells[i], i))));
const rowLabels = computed(() => (current.value?.rows ?? []).map((_, i) => String(i + 1)));
const kindClass = (r: number, c: number) => {
	const k = current.value?.rows[r]?.cells[c]?.kind;
	return k === 'text' ? 'tpl-text' : k === 'late' ? 'tpl-late' : k === 'formula' ? 'warn-cell' : k === 'computed' ? 'tpl-calc' : '';
};

function toCell(v: string): TemplateCell {
	if (v.startsWith('=') && v.length > 1) return { kind: 'formula', value: null, text: v, override: null };
	if (v.includes('F=')) return { kind: 'late', value: null, text: v, override: null };
	if (v.includes('<<')) return { kind: 'text', value: null, text: v, override: null };
	return { kind: 'literal', value: asTyped(v) as Scalar, text: null, override: null };
}

function onSet(edits: CellEdit[]) {
	const t = current.value;
	if (!t) return;
	for (const e of edits) {
		const row = t.rows[e.r];
		if (!row || row.cells[e.c]?.kind === 'computed') continue;
		while (row.cells.length < gen.value.output_columns.length) row.cells.push(toCell(''));
		row.cells[e.c] = toCell(e.value);
	}
}

function blankRow() {
	return {
		cells: gen.value.output_columns.map((c, i) => (c.computed || current.value?.rows[0]?.cells[i]?.kind === 'computed'
			? { kind: 'computed' as const, value: null, text: null, override: current.value?.rows[0]?.cells[i]?.override ?? null }
			: toCell(''))),
		source_row: null,
	};
}

function onInsert(at: number, count: number) {
	current.value?.rows.splice(at, 0, ...Array.from({ length: count }, blankRow));
}

function onRemove(idx: number[]) {
	const t = current.value;
	if (!t) return;
	const drop = new Set(idx);
	t.rows = t.rows.filter((_, i) => !drop.has(i));
}

function addTemplate(copy: boolean) {
	const id = prompt(copy ? `Copy template ${current.value?.id} as ID:` : 'New template ID:')?.trim();
	if (!id) return;
	if (blocks.value.some((b) => b.id === id)) {
		alert(`Template ${id} already exists.`);
		return;
	}
	const idValue: Scalar = asTyped(id);
	const rows = copy && current.value ? JSON.parse(JSON.stringify(current.value.rows)) : [blankRow()];
	gen.value.templates.push({ id, id_value: idValue, rows, duplicate_blocks: 0 });
	g.selectedTemplate = id;
}

function removeTemplate() {
	const t = current.value;
	if (!t) return;
	const used = usage.value[t.id] ?? 0;
	if (!confirm(`Delete template ${t.id}${used ? ` (used by ${used} run(s))` : ''}?`)) return;
	gen.value.templates = gen.value.templates.filter((x) => x.id !== t.id);
	g.selectedTemplate = blocks.value[0]?.id ?? null;
}

// <<TAG>> suggestions: runsheet tags, their _S / _P forms, derived tags, <<PARENT>>
const tagSuggestions = computed(() => {
	const tags = gen.value.runsheet.columns.map((c) => c.tag ?? '').filter(isTag).map((t) => t.trim());
	const out: string[] = [];
	for (const t of tags) {
		out.push(t, `${t.slice(0, -2)}_S>>`);
		if (gen.value.parents) out.push(`${t.slice(0, -2)}_P>>`);
	}
	for (const d of gen.value.derived_tags) out.push(d.name.startsWith('<<') ? d.name : `<<${d.name}>>`);
	const has = (t: string) => tags.some((x) => lower(x) === lower(t));
	if (gen.value.parents && has('<<MECH>>') && has('<<SUF>>')) out.push('<<PARENT>>');
	return [...new Set(out)];
});

// -- live preview -------------------------------------------------------------------

const keyPos = computed(() => {
	const cols = gen.value.runsheet.columns;
	const p = cols.findIndex((c) => lower(c.tag) === lower(gen.value.config.key_placeholder));
	return p >= 0 ? p : cols.findIndex((c) => isTag(c.tag));
});
const runPos = computed(() => gen.value.runsheet.columns.findIndex((c) => lower(c.tag) === lower(gen.value.config.run_placeholder)));
const runs = computed(() => gen.value.runsheet.rows.map((r) => ({
	id: r.id, key: cellText(r.values[keyPos.value] as Scalar), run: runPos.value >= 0 ? cellText(r.values[runPos.value] as Scalar) : '',
})));
const runsUsing = computed(() => runs.value.filter((r) => r.key === current.value?.id));
const previewRun = ref<string>('');
const preview = ref<PreviewResult | null>(null);
watch(current, (t) => {
	if (!t) return;
	if (!runsUsing.value.some((r) => r.id === previewRun.value)) previewRun.value = runsUsing.value[0]?.id ?? runs.value[0]?.id ?? '';
}, { immediate: true });

let timer: ReturnType<typeof setTimeout> | null = null;
async function refreshPreview() {
	if (!current.value || !previewRun.value) {
		preview.value = null;
		return;
	}
	preview.value = (await g.preview(previewRun.value, current.value.id)) ?? null;
}
watch([() => JSON.stringify(current.value), previewRun], () => {
	if (timer) clearTimeout(timer);
	timer = setTimeout(refreshPreview, 350);
}, { immediate: true });
onBeforeUnmount(() => timer && clearTimeout(timer));
// columns worth showing in the preview: any non-empty value
const previewCols = computed(() => {
	const p = preview.value;
	if (!p) return [];
	return p.header.map((h, i) => ({ h, i })).filter(({ i }) => i > 0 && p.rows.some((r) => cellText(r.cells[i]) !== ''));
});
</script>

<template>
	<div class="gen-panel gen-templates">
		<aside class="tpl-list">
			<div class="row">
				<input v-model="filter" type="search" placeholder="Filter templates…" aria-label="Filter templates" />
			</div>
			<ul>
				<li
					v-for="b in shown"
					:key="b.id"
					:class="{ on: current?.id === b.id }"
					@click="g.selectedTemplate = b.id"
				>
					<strong>{{ b.id }}</strong>
					<span class="desc">{{ descOf(b.index) }}</span>
					<span class="meta">
						{{ b.rows }} row{{ b.rows === 1 ? '' : 's' }}
						<template v-if="usage[b.id] !== undefined"> · {{ usage[b.id] ? `${usage[b.id]} run${usage[b.id] === 1 ? '' : 's'}` : 'unused' }}</template>
						<span v-if="b.dups" class="warn" :title="`ID repeated in ${b.dups} later block(s); the first block is used`"> · ⚠ duplicate</span>
					</span>
				</li>
			</ul>
			<div class="row">
				<button type="button" class="secondary small" @click="addTemplate(false)">+ New</button>
				<button type="button" class="secondary small" :disabled="!current" @click="addTemplate(true)">Copy</button>
				<button type="button" class="secondary small" :disabled="!current" @click="removeTemplate">Delete</button>
			</div>
		</aside>
		<section v-if="current" class="tpl-main">
			<div class="tpl-head">
				<strong>Template {{ current.id }}</strong>
				<span class="hint">
					Type <code>&lt;&lt;</code> for tag suggestions · <code>_S</code> removes hyphens, <code>_P</code> gives the parent description ·
					<code>F=</code> starts a late formula · grey <em>ƒ calc</em> columns are calculated
				</span>
			</div>
			<EditGrid
				:columns="columns"
				:cells="cells"
				:row-labels="rowLabels"
				:cell-class="kindClass"
				:history="hist"
				:tag-suggestions="tagSuggestions"
				:height="Math.min(320, 70 + 26 * Math.max(3, current.rows.length))"
				@set="onSet"
				@insert="onInsert"
				@remove="onRemove"
			/>
			<div class="preview">
				<div class="row">
					<strong>Preview</strong>
					<label>for run
						<select v-model="previewRun" aria-label="Run to preview">
							<optgroup v-if="runsUsing.length" :label="`Runs using ${current.id}`">
								<option v-for="r in runsUsing" :key="r.id" :value="r.id">run {{ r.run || '?' }} (row {{ r.id }})</option>
							</optgroup>
							<optgroup label="Any run">
								<option v-for="r in runs" :key="`a-${r.id}`" :value="r.id">run {{ r.run || '?' }} · key {{ r.key || '–' }} (row {{ r.id }})</option>
							</optgroup>
						</select>
					</label>
					<span class="hint">Unsaved edits are included. Hover a value to see its template text.</span>
				</div>
				<p v-if="preview?.message" class="hint">{{ preview.message }}</p>
				<div v-if="preview && preview.rows.length" class="grid-wrap">
					<table class="grid simple preview-table">
						<thead><tr><th v-for="c in previewCols" :key="c.i">{{ c.h }}</th></tr></thead>
						<tbody>
							<tr v-for="(r, k) in preview.rows" :key="k">
								<td
									v-for="c in previewCols"
									:key="c.i"
									:title="r.sources[c.i]"
									:class="{ 'warn-cell': /<<[^<>]*>>/.test(cellText(r.cells[c.i])) }"
								>{{ cellText(r.cells[c.i]) }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</section>
		<p v-else class="hint">No templates yet. Use + New.</p>
	</div>
</template>
