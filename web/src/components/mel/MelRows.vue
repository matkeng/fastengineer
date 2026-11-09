<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import type { PipelineRow } from '../../lib/melTypes';
import { useStage } from '../../lib/useStage';
import { useMel } from '../../stores/mel';

const mel = useMel();
// Rows editor works on the table after column rules (stage 1), before rows are hidden.
const { result } = useStage('columns', (r) => r.columns);
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<PipelineRow> | null = null;
const hiddenCount = ref(0);

const isHidden = (key: string) => mel.draft!.hidden_rows.some((r) => r.key === key);

function setHidden(keys: string[], hide: boolean) {
	const d = mel.draft!;
	const set = new Set(keys);
	d.hidden_rows = d.hidden_rows.filter((r) => !set.has(r.key));
	if (hide) d.hidden_rows.push(...keys.map((key) => ({ key })));
	hiddenCount.value = d.hidden_rows.length;
}

function shownKeys(): string[] {
	return (table?.api.rows({ search: 'applied' }).data().toArray() as PipelineRow[]).map((r) => r.key);
}

function bulk(hide: boolean) {
	setHidden(shownKeys(), hide);
	table?.api.rows().invalidate().draw(false);
}

function build() {
	if (!host.value || !result.value) return;
	table?.api.destroy();
	const r = result.value;
	const columns: ColumnsConfig[] = [
		{
			title: 'Include',
			data: 'key',
			className: 'include-col',
			render: (key: string, type: string) => {
				const on = !isHidden(key);
				if (type === 'display') return `<input type="checkbox" data-key="${escapeHtml(key)}" ${on ? 'checked' : ''} aria-label="Include ${escapeHtml(key)}">`;
				return on ? 'Included' : 'Hidden';
			},
		},
		...r.headers.map((h): ColumnsConfig => ({
			title: escapeHtml(h) + (h === r.key_header ? ' <span class="key-icon">🔑</span>' : ''),
			data: (row: PipelineRow) => row.values[h] ?? '',
			className: h === r.key_header ? 'key-col' : '',
		})),
	];
	table = createFilteredTable<PipelineRow>(host.value, columns.length, {
		data: r.rows,
		columns,
		order: [[1, 'asc']],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [{ extend: 'colvis', text: 'Columns' }],
		language: { search: 'Search all:' },
		createdRow: (tr: HTMLTableRowElement, data: unknown) => {
			tr.classList.toggle('row-off', isHidden((data as PipelineRow).key));
		},
	}, {
		0: {
			options: [{ value: '', label: 'All' }, { value: 'in', label: 'Included' }, { value: 'out', label: 'Hidden' }],
			test: (v, row) => (v === '' ? true : (v === 'out') === isHidden(row.key)),
		},
	});
	hiddenCount.value = mel.draft!.hidden_rows.length;
}

function onChange(e: Event) {
	const el = e.target as HTMLInputElement;
	if (!el.dataset.key) return;
	setHidden([el.dataset.key], !el.checked);
	el.closest('tr')?.classList.toggle('row-off', !el.checked);
}

watch([result, host], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<div class="results mel-grid">
		<div class="row">
			<span class="hint">Untick rows that are not loads (notes, spares, tanks…). Rows are matched by key, so the choice carries over to revised files.</span>
			<span class="spacer" />
			<span class="chip"><strong>{{ hiddenCount }}</strong> hidden</span>
			<button type="button" class="secondary small" @click="bulk(false)">Include all shown</button>
			<button type="button" class="secondary small" @click="bulk(true)">Hide all shown</button>
		</div>
		<div ref="host" class="result-table" @change="onChange" />
	</div>
</template>
