<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import type { PipelineRow } from '../../lib/melTypes';
import { useStage } from '../../lib/useStage';
import { useMel } from '../../stores/mel';
import AppModal from '../common/AppModal.vue';

const mel = useMel();
// Overrides apply to the table after text columns (stage 3).
const { result } = useStage('text', (r) => [r.columns, r.hidden_rows, r.text_columns]);
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<PipelineRow> | null = null;
const count = computed(() => mel.draft!.overrides.length);

const editing = ref<{ key: string; column: string; original: string; value: string; note: string; rowIdx: number } | null>(null);

const find = (key: string, column: string) => mel.draft!.overrides.find((o) => o.key === key && o.column === column);

function build() {
	if (!host.value || !result.value) return;
	table?.api.destroy();
	const r = result.value;
	const columns: ColumnsConfig[] = r.headers.map((h): ColumnsConfig => ({
		title: escapeHtml(h) + (h === r.key_header ? ' <span class="key-icon">🔑</span>' : ''),
		data: (row: PipelineRow) => row.values[h] ?? '',
		className: h === r.key_header ? 'key-col' : 'editable',
		render: (value: string, type: string, row: PipelineRow) => {
			const ov = h === r.key_header ? undefined : find(row.key, h);
			if (type !== 'display') return ov ? ov.value : value;
			if (!ov) return escapeHtml(value);
			const why = ov.note ? `\nReason: ${ov.note}` : '';
			return `<span class="ov" title="Was: ${escapeHtml(value || '(blank)')}${escapeHtml(why)}">${escapeHtml(ov.value) || '<em>blank</em>'}</span>`;
		},
	}));
	table = createFilteredTable<PipelineRow>(host.value, columns.length, {
		data: r.rows,
		columns,
		order: [[0, 'asc']],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [{ extend: 'colvis', text: 'Columns' }],
		language: { search: 'Search all:' },
	});
}

function onClick(e: MouseEvent) {
	const td = (e.target as HTMLElement).closest('tbody td') as HTMLTableCellElement | null;
	if (!td || !table || !result.value) return;
	const idx = table.api.cell(td).index();
	if (!idx) return;
	const header = result.value.headers[idx.column];
	if (header === result.value.key_header) return;
	const row = table.api.row(idx.row).data() as PipelineRow;
	const original = row.values[header] ?? '';
	const ov = find(row.key, header);
	editing.value = { key: row.key, column: header, original, value: ov?.value ?? original, note: ov?.note ?? '', rowIdx: idx.row };
}

function apply(clear = false) {
	const e = editing.value;
	if (!e) return;
	const d = mel.draft!;
	d.overrides = d.overrides.filter((o) => !(o.key === e.key && o.column === e.column));
	// Typing the original value back removes the override (PRD 5.7).
	if (!clear && e.value !== e.original) d.overrides.push({ key: e.key, column: e.column, value: e.value, ...(e.note.trim() ? { note: e.note.trim() } : {}) });
	table?.api.row(e.rowIdx).invalidate().draw(false);
	editing.value = null;
}

function clearAll() {
	if (confirm(`Remove all ${count.value} overrides?`)) {
		mel.draft!.overrides = [];
		table?.api.rows().invalidate().draw(false);
	}
}

watch([result, host], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<div class="results mel-grid">
		<div class="row">
			<span class="hint">Click a cell to change its value without editing the file, with a reason for the edits report. Overridden cells are orange; hover to see the file's value.</span>
			<span class="spacer" />
			<span class="chip"><strong>{{ count }}</strong> overrides</span>
			<button v-if="count" type="button" class="secondary small" @click="clearAll">Clear all</button>
		</div>
		<div ref="host" class="result-table overrides" @click="onClick" />
		<AppModal :open="!!editing" title="Override cell" @close="editing = null">
			<template v-if="editing">
				<p><strong>{{ editing.key }}</strong> · {{ editing.column }}</p>
				<p class="hint">Value in the file: <code>{{ editing.original || '(blank)' }}</code></p>
				<label class="field">New value <input v-model="editing.value" autofocus @keydown.enter.prevent="apply()" /></label>
				<label class="field">Reason <span class="hint small">(for the edits report, e.g. "Upsized per vendor data")</span>
					<input v-model="editing.note" placeholder="Why the file's value is changed" @keydown.enter.prevent="apply()" /></label>
			</template>
			<template #footer>
				<button type="button" class="secondary" @click="apply(true)">Clear override</button>
				<span class="spacer" />
				<button type="button" class="secondary" @click="editing = null">Cancel</button>
				<button type="button" @click="apply()">Apply</button>
			</template>
		</AppModal>
	</div>
</template>
