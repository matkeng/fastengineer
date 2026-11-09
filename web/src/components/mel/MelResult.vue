<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import type { LoadListResult, PipelineResult, PipelineRow } from '../../lib/melTypes';
import { useMel } from '../../stores/mel';

const mel = useMel();
const view = ref<'combined' | 'loadlist'>('combined');
const combined = ref<PipelineResult | null>(null);
const ll = ref<LoadListResult | null>(null);
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<unknown> | null = null;

async function load() {
	combined.value = (await mel.runStage('auto')) ?? null;
	ll.value = (await mel.loadList()) ?? null;
}

function build() {
	if (!host.value) return;
	table?.api.destroy();
	table = null;
	const buttons = [{ extend: 'colvis', text: 'Columns' }, { extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible' } }];
	if (view.value === 'combined' && combined.value) {
		const r = combined.value;
		const autos = new Set(mel.draft!.auto_columns.map((a) => a.name));
		const columns: ColumnsConfig[] = r.headers.map((h): ColumnsConfig => ({
			title: escapeHtml(h) + (h === r.key_header ? ' <span class="key-icon">🔑</span>' : autos.has(h) ? ' <span class="col-badge calc">calc</span>' : ''),
			data: (row: PipelineRow) => row.values[h] ?? '',
			className: h === r.key_header ? 'key-col' : '',
			createdCell: (td: HTMLTableCellElement, _v: unknown, row: PipelineRow) => {
				if (row.overridden.includes(h)) { td.classList.add('ov-cell'); td.title = 'Overridden'; }
				if (row.auto_errors.includes(h)) td.classList.add('err-cell');
			},
		}));
		table = createFilteredTable<PipelineRow>(host.value, columns.length, {
			data: r.rows, columns, order: [[0, 'asc']], pageLength: 50, lengthMenu: [25, 50, 100, 500],
			layout: TOOLBAR_LAYOUT, buttons, language: { search: 'Search all:' },
			createdRow: (tr: HTMLTableRowElement, data: unknown) => { if ((data as PipelineRow).origin === 'custom') tr.classList.add('row-custom'); },
		}) as FilteredTable<unknown>;
	} else if (view.value === 'loadlist' && ll.value) {
		const l = ll.value;
		const columns: ColumnsConfig[] = l.fields.map((f): ColumnsConfig => ({
			title: escapeHtml(f), data: (row: Record<string, unknown>) => row[f] ?? '',
			render: (v: unknown, type: string) => (type === 'display' ? escapeHtml(v === null || v === undefined ? '' : String(v)) : v),
		}));
		if (!columns.length) { host.value.innerHTML = '<p class="hint">Nothing is mapped yet: set up the Mapping tab first.</p>'; return; }
		table = createFilteredTable(host.value, columns.length, {
			data: l.rows, columns, order: [[0, 'asc']], pageLength: 50, lengthMenu: [25, 50, 100, 500],
			layout: TOOLBAR_LAYOUT, buttons, language: { search: 'Search all:' },
		});
	}
}

onMounted(load);
watch([view, combined, ll, host], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<div class="results mel-grid">
		<div class="row">
			<div class="seg">
				<button type="button" :class="view === 'combined' ? '' : 'secondary'" @click="view = 'combined'">
					Combined table <span class="count">{{ combined?.rows.length ?? '…' }}</span>
				</button>
				<button type="button" :class="view === 'loadlist' ? '' : 'secondary'" @click="view = 'loadlist'">
					{{ mel.outputName }} <span class="count">{{ ll?.fields.length ?? 0 }} fields</span>
				</button>
			</div>
			<span class="spacer" />
			<span class="hint">Export {{ view === 'combined' ? 'combined table' : mel.outputName.toLowerCase() }}:</span>
			<button type="button" class="secondary" :disabled="mel.busy" @click="mel.exportTable(view, 'csv')">CSV</button>
			<button type="button" :disabled="mel.busy" @click="mel.exportTable(view, 'xlsx')">Excel (.xlsx)</button>
		</div>
		<div v-if="combined?.issues.length || ll?.warnings.length" class="chips">
			<span v-for="i in combined?.issues ?? []" :key="i.kind + i.rule + i.message" class="chip warn-chip">⚠ {{ i.kind }} · {{ i.rule }}: {{ i.message }}</span>
			<span v-for="w in view === 'loadlist' ? ll?.warnings ?? [] : []" :key="w" class="chip warn-chip">⚠ {{ w }}</span>
		</div>
		<p v-if="view === 'combined'" class="legend small">
			<span class="swatch ov" /> overridden <span class="swatch custom" /> custom row <span class="swatch err" /> calculation error
		</p>
		<div ref="host" class="result-table" />
	</div>
</template>
