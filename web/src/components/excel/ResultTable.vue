<script setup lang="ts">
import type { ColumnsConfig, Config } from 'datatables.net';
import DataTable, { type Api } from 'datatables.net-dt';
import 'datatables.net-buttons-dt';
import 'datatables.net-buttons/js/buttons.colVis.mjs';
import 'datatables.net-buttons/js/buttons.html5.mjs';
import 'datatables.net-dt/css/dataTables.dataTables.css';
import 'datatables.net-buttons-dt/css/buttons.dataTables.css';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { STRIKE_LABELS, cellHtml, escapeHtml } from '../../lib/cells';
import type { Cell, ExtractResult, ExtractedRow, Strike } from '../../lib/types';

const props = defineProps<{ result: ExtractResult }>();
const host = ref<HTMLDivElement | null>(null);
let table: Api<ExtractedRow> | null = null;

// Strike filter choices for the "Strike" column.
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

	const el = document.createElement('table');
	el.className = 'display compact stripe hover';
	el.style.width = '100%';
	// Two header rows: titles (sortable) and, below them, the column filters.
	const head = el.createTHead();
	const titles = head.insertRow();
	const filters = head.insertRow();
	filters.className = 'filters';
	columns.forEach(() => {
		titles.appendChild(document.createElement('th'));
		const th = document.createElement('th');
		th.className = 'dt-orderable-none';
		filters.appendChild(th);
	});
	host.value.replaceChildren(el);

	const strikeIdx = columns.length - 2;
	const options: Config = {
		data: r.rows,
		columns,
		order: [[0, 'asc']],
		titleRow: 0, // titles go in the first header row; the second holds filters
		pageLength: 25,
		lengthMenu: [10, 25, 50, 100, 500],
		// No scrollX: it splits header/body/footer into separate tables sized once at
		// start-up. One table inside a scrolling cell (see style.css) stays aligned
		// and follows the window size.
		autoWidth: false,
		// 'buttons' is a layout feature added by the Buttons extension.
		layout: {
			topStart: ['pageLength', 'buttons'],
			topEnd: 'search',
		} as unknown as Config['layout'],
		buttons: [
			{ extend: 'colvis', text: 'Columns', columns: ':not(.noVis)' },
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
		initComplete() {
			const api = this.api();
			const filterCells = el.querySelectorAll<HTMLTableCellElement>('thead tr.filters th');
			api.columns().every(function (idx) {
				const cell = filterCells[idx];
				// Typing or clicking in a filter must not sort the column.
				for (const ev of ['click', 'keydown', 'mousedown']) cell.addEventListener(ev, (e) => e.stopPropagation());
				if (idx === strikeIdx) {
					const select = document.createElement('select');
					select.innerHTML = `
						<option value="">All rows</option>
						<option value="none">No strike</option>
						<option value="any">Any strike</option>
						<option value="partial">Partly struck</option>
						<option value="full">Struck out</option>
						<option value="not-full">Hide struck-out rows</option>`;
					select.addEventListener('change', () => {
						const test = STRIKE_FILTERS[select.value];
						this.search((_d: string | null, row: ExtractedRow) => test(row.strike)).draw();
					});
					cell.replaceChildren(select);
					return;
				}
				const input = document.createElement('input');
				input.type = 'search';
				input.placeholder = 'Filter…';
				input.addEventListener('input', () => {
					if (this.search() !== input.value) this.search(input.value).draw();
				});
				cell.replaceChildren(input);
			});
		},
	};
	table = new DataTable<ExtractedRow>(el, options);
}

function destroy() {
	table?.destroy();
	table = null;
}

onMounted(build);
watch(() => props.result, build);
onBeforeUnmount(destroy);
</script>

<template>
	<div ref="host" class="result-table" />
</template>
