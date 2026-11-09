<script setup lang="ts">
import type { ColumnsConfig, Config } from 'datatables.net';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { STATUS_LABELS, type StatusFilter, cellHtml, escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import type { Cell, CompareCell, CompareColumn, CompareResult, CompareRow, RowStatus } from '../../lib/types';

const props = defineProps<{ result: CompareResult }>();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<CompareRow> | null = null;

const STATUS_COL = 0;

function valueHtml(c: Cell | null): string {
	if (!c || !c.t.trim()) return '<em class="blank">blank</em>';
	return cellHtml(c);
}

function render(c: CompareCell, type: string): string | number {
	const shown = c.b ?? c.a;
	if (type === 'display') {
		if (c.change === 'none') return shown ? cellHtml(shown) : '';
		// Short diffs stay on one line; long text may wrap.
		const long = (c.a?.t.length ?? 0) + (c.b?.t.length ?? 0) > 36;
		return `<span class="diff${long ? ' long' : ''}"><span class="old" title="Old value">${valueHtml(c.a)}</span><span class="arrow">→</span><span class="new" title="New value">${valueHtml(c.b)}</span></span>`;
	}
	if (type === 'sort' || type === 'type') {
		if (!shown) return '';
		return typeof shown.v === 'number' ? shown.v : shown.t.toLowerCase();
	}
	if (type === 'filter') return [c.a?.t, c.b?.t].filter(Boolean).join(' ');
	// export
	if (c.change === 'none') return shown?.t ?? '';
	return `${c.a?.t ?? ''} → ${c.b?.t ?? ''}`;
}

function columnTitle(col: CompareColumn): string {
	let html = escapeHtml(col.name);
	if (col.is_key) html += ' <span class="key-icon" title="Key column">🔑</span>';
	if (col.status === 'added') html += ' <span class="col-badge added" title="Only in the new table">new column</span>';
	if (col.status === 'deleted') html += ' <span class="col-badge deleted" title="Only in the old table">removed column</span>';
	if (col.status === 'same' && col.old_name && col.old_name !== col.name)
		html += ` <span class="col-badge renamed" title="Old name: ${escapeHtml(col.old_name)}">renamed</span>`;
	return html;
}

function build() {
	if (!host.value) return;
	destroy();
	const r = props.result;
	const keyIdx = r.columns.findIndex((c) => c.is_key);
	const others = r.columns.map((_, i) => i).filter((i) => i !== keyIdx);

	const dataCol = (i: number): ColumnsConfig => {
		const col = r.columns[i];
		return {
			title: columnTitle(col),
			data: (row: CompareRow) => row.cells[i],
			render: (c: CompareCell, type: string) => render(c, type),
			className: [col.is_key ? 'key-col' : '', col.status !== 'same' ? `col-${col.status}` : ''].join(' '),
			createdCell: (td: HTMLTableCellElement, c: CompareCell) => {
				if (c.change !== 'none') td.classList.add('chg', `chg-${c.change}`);
			},
		};
	};

	const columns: ColumnsConfig[] = [
		{
			title: 'Status',
			data: 'status',
			className: 'status-col',
			render: (s: RowStatus, type: string) =>
				type === 'display' ? `<span class="status-badge ${s}">${STATUS_LABELS[s]}</span>` : STATUS_LABELS[s],
		},
		dataCol(keyIdx),
		...others.map(dataCol),
		{ title: 'Changes', data: 'changed_cells', className: 'dt-right', render: (n: number, t: string) => (t === 'display' && !n ? '' : n) },
		{ title: 'Old row', data: 'a_row', className: 'dt-right', render: (n: number | null) => n ?? '' },
		{ title: 'New row', data: 'b_row', className: 'dt-right', render: (n: number | null) => n ?? '' },
	];
	// Columns whose cells never changed (added/removed columns and the key always stay).
	// others[j] is table column 2 + j (after Status and the key).
	const quiet = others
		.map((i, j) => ({ col: r.columns[i], tableIdx: 2 + j }))
		.filter(({ col }) => col.status === 'same' && col.changed_cells === 0)
		.map(({ tableIdx }) => tableIdx);

	let onlyChanged = false;
	const buttons = [
		{ extend: 'colvis', text: 'Columns' },
		{
			text: 'Changed columns only',
			className: 'toggle-changed',
			action(this: { text: (t: string) => void; active: (a: boolean) => void }, _e: Event, dt: { columns: (s: number[]) => { visible: (v: boolean) => void } }) {
				onlyChanged = !onlyChanged;
				dt.columns(quiet).visible(!onlyChanged);
				this.active(onlyChanged);
				this.text(onlyChanged ? 'All columns' : 'Changed columns only');
			},
		},
		{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
		{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: 'table-compare' },
	] as unknown as Config['buttons'];

	table = createFilteredTable<CompareRow>(
		host.value,
		columns.length,
		{
			data: r.rows,
			columns,
			order: [[1, 'asc']],
			pageLength: 25,
			lengthMenu: [10, 25, 50, 100, 500],
			layout: TOOLBAR_LAYOUT,
			buttons,
			language: { search: 'Search all:', searchPlaceholder: 'Old or new values…' },
			createdRow: (tr: HTMLTableRowElement, data: unknown) => {
				const row = data as CompareRow;
				tr.classList.add(`row-${row.status}`);
				if (row.duplicate_key) tr.classList.add('dup-key');
			},
		},
		{
			[STATUS_COL]: {
				options: [
					{ value: 'changes', label: 'Any change' },
					{ value: '', label: 'All rows' },
					...Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label })),
				],
				initial: 'changes',
				test: (v, row) => (v === '' ? true : v === 'changes' ? row.status !== 'unchanged' : row.status === v),
			},
		},
	);
}

function destroy() {
	table?.api.destroy();
	table = null;
}

/** Used by the summary chips. */
function setStatusFilter(value: StatusFilter) {
	table?.setSelect(STATUS_COL, value);
}
defineExpose({ setStatusFilter });

onMounted(build);
watch(() => props.result, build);
onBeforeUnmount(destroy);
</script>

<template>
	<div ref="host" class="result-table compare-table" />
</template>
