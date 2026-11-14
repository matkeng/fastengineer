<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The runsheet: one row per run. Row 1 of the header is the label, row 2 the <<TAG>>.
import { computed, nextTick, ref, watch } from 'vue';
import { type Scalar, asTyped, cellText, isTag } from '../../lib/genTypes';
import { useGenerators } from '../../stores/generators';
import EditGrid, { type CellEdit, type GridColumn } from '../common/EditGrid.vue';
import { useUndo } from '../../lib/history';

const g = useGenerators();
const grid = ref<InstanceType<typeof EditGrid> | null>(null);
const gen = computed(() => g.draft!.generator);
// Undo for the grid: back to the runsheet as it was before each edit, until it is saved or loaded again.
const hist = useUndo({ get: () => g.draft?.generator.runsheet, resetOn: () => g.saved });
const cfg = computed(() => gen.value.config);
const cols = computed(() => gen.value.runsheet.columns);
const rows = computed(() => gen.value.runsheet.rows);
const lower = (s: string | null | undefined) => (s ?? '').trim().toLowerCase();
const posOf = (tag: string) => cols.value.findIndex((c) => lower(c.tag) === lower(tag));
const keyPos = computed(() => {
	const p = posOf(cfg.value.key_placeholder);
	return p >= 0 ? p : cols.value.findIndex((c) => isTag(c.tag));
});
const runPos = computed(() => posOf(cfg.value.run_placeholder));
const lockPos = computed(() => posOf(cfg.value.locked_placeholder));
const templateIds = computed(() => [...new Set(gen.value.templates.map((t) => t.id))]);
const parentTags = computed(() => (gen.value.parents ?? []).slice(0, 3000).map((p) => p[0]));
// columns whose value is looked up on Parents (<<X_P>> used, or <<MECH>> for <<PARENT>>)
const parentCols = computed(() => {
	const used = new Set<string>();
	for (const t of gen.value.templates) for (const r of t.rows) for (const c of r.cells) {
		for (const m of (c.text ?? '').matchAll(/<<([^<>]+)_P>>/gi)) used.add(`<<${m[1].toLowerCase()}>>`);
		if (/<<PARENT>>/i.test(c.text ?? '')) used.add('<<mech>>');
	}
	return used;
});

const columns = computed<GridColumn[]>(() => cols.value.map((c, i) => {
	const tag = c.tag ?? '';
	const calc = !!c.formula;
	return {
		label: c.name || tag || `Column ${i + 1}`,
		sub: isTag(tag) ? tag : '',
		type: i === lockPos.value ? 'bool' : 'text',
		readonly: calc,
		badge: calc ? 'calc' : i === keyPos.value ? 'key' : undefined,
		title: calc ? `Calculated in the workbook: ${c.formula}` : (i === keyPos.value ? 'Selects the template' : tag),
		options: i === keyPos.value ? [...templateIds.value, 'nr'] : parentCols.value.has(lower(tag)) ? parentTags.value : undefined,
		width: i === keyPos.value ? 90 : i === runPos.value ? 70 : i === lockPos.value ? 70 : isTag(tag) && /^<<#\d+>>$/.test(tag) ? 80 : 150,
	};
}));

const cells = computed(() => rows.value.map((r) => cols.value.map((_, i) => cellText(r.values[i] as Scalar))));
const rowLabels = computed(() => rows.value.map((r) => (r.id.startsWith('new-') ? 'new' : r.id)));

function keyClass(r: number, c: number): string {
	if (c !== keyPos.value) return '';
	const k = cells.value[r][c].trim();
	if (!k || ['nr', 'none'].includes(k.toLowerCase())) return 'muted-cell';
	return templateIds.value.includes(k) ? '' : 'warn-cell';
}

function onSet(edits: CellEdit[]) {
	for (const e of edits) {
		const row = rows.value[e.r];
		if (!row) continue;
		while (row.values.length < cols.value.length) row.values.push(null);
		row.values[e.c] = e.c === lockPos.value ? (e.value ? true : null) : asTyped(e.value);
	}
}

let seq = 0;
function onInsert(at: number, count: number) {
	const runs = rows.value.map((r) => Number(r.values[runPos.value])).filter((n) => Number.isFinite(n));
	let next = runs.length ? Math.max(...runs) + 1 : 1;
	const added = Array.from({ length: count }, () => {
		const values: Scalar[] = cols.value.map(() => null);
		if (runPos.value >= 0) values[runPos.value] = next++;
		return { id: `new-${Date.now().toString(36)}-${seq++}`, values };
	});
	rows.value.splice(at, 0, ...added);
}

function onRemove(idx: number[]) {
	const drop = new Set(idx);
	gen.value.runsheet.rows = rows.value.filter((_, i) => !drop.has(i));
}

const missing = computed(() => {
	if (keyPos.value < 0) return 0;
	return cells.value.filter((r) => {
		const k = r[keyPos.value].trim();
		return k && !['nr', 'none'].includes(k.toLowerCase()) && !templateIds.value.includes(k);
	}).length;
});

watch(() => g.jumpToRow, async (id) => {
	if (!id) return;
	const i = rows.value.findIndex((r) => r.id === id);
	g.jumpToRow = null;
	await nextTick();
	if (i >= 0) grid.value?.select(i, Math.max(0, keyPos.value));
}, { immediate: true });
</script>

<template>
	<div class="gen-panel">
		<div class="row">
			<span class="chip"><strong>{{ rows.length }}</strong> runs</span>
			<span class="chip">key {{ cfg.key_placeholder }}</span>
			<span v-if="cfg.run_from !== null || cfg.run_up_to !== null" class="chip" title="RunUpTo is exclusive">
				runs {{ cfg.run_from ?? '…' }} to below {{ cfg.run_up_to ?? '…' }}
			</span>
			<span v-if="missing" class="chip warn" title="Keys with no template are highlighted">{{ missing }} without a template</span>
			<span class="hint">Pick the template in the key column; blank, <em>nr</em> or <em>none</em> skips the run.</span>
		</div>
		<EditGrid
			ref="grid"
			:columns="columns"
			:cells="cells"
			:row-labels="rowLabels"
			:cell-class="keyClass"
			:history="hist"
			@set="onSet"
			@insert="onInsert"
			@remove="onRemove"
		/>
	</div>
</template>
