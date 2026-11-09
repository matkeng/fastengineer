<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Build the output, see what changed since the previous build, export.
import type { ColumnsConfig } from 'datatables.net';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { type OutputRow, type Scalar, cellText } from '../../lib/genTypes';
import { useGenerators } from '../../stores/generators';

const g = useGenerators();
const cfg = computed(() => g.draft!.generator.config);
const runFrom = ref<string>('');
const runBelow = ref<string>('');
watch(() => g.draft?.id, () => {
	runFrom.value = cfg.value.run_from === null ? '' : String(cfg.value.run_from);
	runBelow.value = cfg.value.run_up_to === null ? '' : String(cfg.value.run_up_to);
}, { immediate: true });
const num = (s: string) => (s.trim() === '' || !Number.isFinite(Number(s)) ? null : Number(s));

const view = ref<'output' | 'changes'>('output');
const b = computed(() => g.build);
const info = computed(() => b.value?.info ?? null);
const trace = ref<OutputRow | null>(null);
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<unknown> | null = null;

interface ChangeLine { kind: string; key: string; column: string; old: Scalar; new: Scalar }
const changeLines = computed<ChangeLine[]>(() => {
	const ch = b.value?.result.changes;
	if (!ch) return [];
	const out: ChangeLine[] = [];
	for (const e of ch.entries) {
		if (e.kind !== 'changed') out.push({ kind: e.kind, key: e.key, column: '', old: null, new: null });
		else for (const c of e.cells) out.push({ kind: 'changed', key: e.key, column: c.column, old: c.old, new: c.new });
	}
	return out;
});

const render = (v: Scalar) => escapeHtml(cellText(v));

function draw() {
	table?.api.destroy();
	table = null;
	trace.value = null;
	if (!host.value || !b.value) return;
	if (view.value === 'output') {
		const r = b.value.result;
		const columns: ColumnsConfig[] = r.header.map((h, i) => ({
			title: escapeHtml(h),
			data: (row: OutputRow) => row.cells[i] ?? null,
			render: (v: Scalar, type: string) => (type === 'display' ? render(v) : cellText(v)),
			className: h === cfg.value.diff_key ? 'key-col' : '',
		}));
		table = createFilteredTable<OutputRow>(host.value, columns.length, {
			data: r.rows,
			columns,
			ordering: false, // keep the build order (runs, then template rows)
			pageLength: 100,
			lengthMenu: [50, 100, 500, 2000],
			layout: TOOLBAR_LAYOUT,
			buttons: [{ extend: 'colvis', text: 'Columns' }],
			language: { search: 'Search all:' },
			createdRow: (tr: HTMLTableRowElement, data: unknown) => {
				const row = data as OutputRow;
				tr.classList.toggle('sep-row', row.run_row_id === null);
				tr.classList.toggle('locked-row', row.locked);
				tr.dataset.trace = '1';
			},
		}) as FilteredTable<unknown>;
	} else {
		const columns: ColumnsConfig[] = [
			{ title: 'Change', data: 'kind', render: (v: string, t: string) => (t === 'display' ? `<span class="chg chg-${v}">${v}</span>` : v) },
			{ title: escapeHtml(cfg.value.diff_key), data: 'key', className: 'key-col', render: (v: string) => escapeHtml(v) },
			{ title: 'Column', data: 'column', render: (v: string) => escapeHtml(v) },
			{ title: 'Old', data: 'old', render: (v: Scalar) => render(v) },
			{ title: 'New', data: 'new', render: (v: Scalar) => render(v) },
		];
		table = createFilteredTable<ChangeLine>(host.value, columns.length, {
			data: changeLines.value,
			columns,
			pageLength: 100,
			layout: TOOLBAR_LAYOUT,
			buttons: [],
		}, {
			0: {
				options: [{ value: '', label: 'All' }, { value: 'added', label: 'Added' }, { value: 'removed', label: 'Removed' }, { value: 'changed', label: 'Changed' }],
				test: (v, row) => !v || row.kind === v,
			},
		}) as FilteredTable<unknown>;
	}
}

watch([b, view, host], () => void nextTick(draw));
onBeforeUnmount(() => table?.api.destroy());

function onClick(e: MouseEvent) {
	if (view.value !== 'output' || !table) return;
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (tr) trace.value = (table.api.row(tr as HTMLTableRowElement).data() as OutputRow) ?? null;
}

const traceText = computed(() => {
	const t = trace.value;
	if (!t || !t.run_row_id) return '';
	return `runsheet row ${t.run_row_id} · template ${t.template_id} row ${t.template_seq}${t.locked ? ' · copied from the previous build (locked run)' : ''}`;
});

async function doBuild() {
	await g.startBuild(num(runFrom.value), num(runBelow.value));
	view.value = info.value?.added !== null && info.value && (info.value.added || info.value.removed || info.value.changed) ? 'changes' : 'output';
}

function removeBuild() {
	if (info.value && confirm(`Delete build ${info.value.seq}? The next build will compare with the one before it.`)) void g.deleteBuild(info.value.id);
}

const warnings = computed(() => (info.value?.warnings ?? []).filter((w) => w.code !== 'unresolvedTokens'));
</script>

<template>
	<div class="gen-panel gen-build">
		<div class="row">
			<label>From run <input v-model="runFrom" class="num" inputmode="decimal" placeholder="first" /></label>
			<label title="Runs below this number are built (this number itself is not)">Run below <input v-model="runBelow" class="num" inputmode="decimal" placeholder="no limit" /></label>
			<button type="button" :disabled="g.busy" @click="doBuild">{{ g.dirty ? 'Save and build' : 'Run build' }}</button>
			<span class="spacer" />
			<label v-if="g.builds.length">Build
				<select :value="info?.id" aria-label="Build history" @change="g.loadBuild(($event.target as HTMLSelectElement).value)">
					<option v-for="x in g.builds" :key="x.id" :value="x.id">{{ x.seq }} · {{ new Date(x.created_at).toLocaleString() }} · {{ x.stats.rows_written }} rows</option>
				</select>
			</label>
			<button type="button" class="secondary small" :disabled="!info" @click="removeBuild">Delete build</button>
			<button type="button" class="secondary" :disabled="!info || g.busy" @click="g.exportBuild('xlsx')">Export .xlsx</button>
			<button type="button" class="secondary" :disabled="!info || g.busy" @click="g.exportBuild('csv')">.csv</button>
		</div>
		<template v-if="info">
			<div class="row stats">
				<span class="chip"><strong>{{ info.stats.processed }}</strong> runs</span>
				<span class="chip"><strong>{{ info.stats.rows_written }}</strong> rows</span>
				<span class="chip">{{ info.stats.non_empty_cells }} cells</span>
				<span v-if="info.stats.no_template" class="chip warn">{{ info.stats.no_template }} run{{ info.stats.no_template === 1 ? '' : 's' }} without a template</span>
				<span v-if="info.stats.skipped" class="chip">{{ info.stats.skipped }} not required</span>
				<span v-if="info.stats.filtered" class="chip">{{ info.stats.filtered }} outside the run range</span>
				<span v-if="info.stats.locked_used" class="chip">{{ info.stats.locked_used }} locked</span>
				<span v-if="info.unresolved_count" class="chip warn" :title="info.unresolved_tokens.join(', ')">{{ info.unresolved_count }} unresolved tags</span>
				<span class="chip" :title="info.engine_version">{{ info.stats.duration_ms.toFixed(0) }} ms</span>
				<span v-if="info.added === null" class="hint">First build: nothing to compare with.</span>
				<span v-else class="chip" :class="{ ok: !info.added && !info.removed && !info.changed }">
					+{{ info.added }} added · −{{ info.removed }} removed · ~{{ info.changed }} changed
				</span>
			</div>
			<ul v-if="warnings.length" class="warn-list">
				<li v-for="(w, i) in warnings" :key="i"><strong>{{ w.item }}</strong> {{ w.detail }}</li>
			</ul>
			<nav class="subtabs small">
				<button type="button" :class="{ active: view === 'output' }" @click="view = 'output'">Output</button>
				<button type="button" :class="{ active: view === 'changes' }" :disabled="info.added === null" @click="view = 'changes'">
					Changes<span v-if="changeLines.length" class="count">{{ changeLines.length }}</span>
				</button>
			</nav>
			<p v-if="view === 'output'" class="hint trace">{{ traceText || 'Click a row to see which run and template row it came from.' }}</p>
			<div ref="host" class="result-table gen-output" @click="onClick" />
		</template>
		<p v-else class="hint">No build yet. Press Run build.</p>
	</div>
</template>
