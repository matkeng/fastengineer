<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { STRIKE_LABELS, cellHtml, escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import type { Cell, ExtractResult, ExtractedRow, Strike } from '../../lib/types';

const props = defineProps<{ result: ExtractResult }>();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<ExtractedRow> | null = null;

const STRIKE_FILTERS: Record<string, (s: Strike) => boolean> = {
	'': () => true,
	none: (s) => s === 'none',
	any: (s) => s !== 'none',
	partial: (s) => s === 'partial',
	full: (s) => s === 'full',
	'not-full': (s) => s !== 'full',
};

function cellRender(cell: Cell, type: string): string | number {
	if (type === 'display') return cellHtml(cell);
	if (type === 'sort' || type === 'type') return typeof cell.v === 'number' ? cell.v : cell.t.toLowerCase();
	return cell.t; // filter + export: plain text
}

function build() {
	if (!host.value) return;
	destroy();
	const r = props.result;
	const key = r.key_column;
	// Key column first, then the rest in sheet order.
	const order = [key, ...r.columns.map((c) => c.index).filter((i) => i !== key)];

	const columns: ColumnsConfig[] = [
		...order.map((i): ColumnsConfig => ({
			title: escapeHtml(r.columns[i].name) + (i === key ? ' <span class="key-icon" title="Key column">🔑</span>' : ''),
			data: (row: ExtractedRow) => row.cells[i],
			render: (cell: Cell, type: string) => cellRender(cell, type),
			className: i === key ? 'key-col' : '',
		})),
		{
			title: 'Strike',
			data: 'strike',
			render: (s: Strike, type: string) =>
				type === 'display' ? `<span class="strike-badge ${s}">${STRIKE_LABELS[s]}</span>` : STRIKE_LABELS[s],
		},
		{ title: 'Excel row', data: 'row', className: 'dt-right' },
	];

	table = createFilteredTable<ExtractedRow>(
		host.value,
		columns.length,
		{
			data: r.rows,
			columns,
			order: [[0, 'asc']],
			pageLength: 25,
			lengthMenu: [10, 25, 50, 100, 500],
			layout: TOOLBAR_LAYOUT,
			buttons: [
				{ extend: 'colvis', text: 'Columns' },
				{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
				{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' },
					filename: `${r.source.name}-extract` },
			],
			language: { search: 'Search all:', searchPlaceholder: 'Any column…' },
			createdRow: (tr: HTMLTableRowElement, data: unknown) => {
				const row = data as ExtractedRow;
				if (row.duplicate_key) tr.classList.add('dup-key');
				if (row.strike === 'full') tr.classList.add('row-struck');
			},
		},
		{
			[columns.length - 2]: {
				options: [
					{ value: '', label: 'All rows' },
					{ value: 'none', label: 'No strike' },
					{ value: 'any', label: 'Any strike' },
					{ value: 'partial', label: 'Partly struck' },
					{ value: 'full', label: 'Struck out' },
					{ value: 'not-full', label: 'Hide struck-out rows' },
				],
				test: (v, row) => STRIKE_FILTERS[v](row.strike),
			},
		},
	);
}

function destroy() {
	table?.api.destroy();
	table = null;
}

onMounted(build);
watch(() => props.result, build);
onBeforeUnmount(destroy);
</script>

<template>
	<div ref="host" class="result-table" />
</template>
