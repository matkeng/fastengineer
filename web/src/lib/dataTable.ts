// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Shared DataTables set-up: a table whose header has a title row (sortable)
// and a filter row, inside a scrolling cell that follows the window size.
import type { Config } from 'datatables.net';
import DataTable, { type Api } from 'datatables.net-dt';
import 'datatables.net-buttons-dt';
import 'datatables.net-buttons/js/buttons.colVis.mjs';
import 'datatables.net-buttons/js/buttons.html5.mjs';
import 'datatables.net-dt/css/dataTables.dataTables.css';
import 'datatables.net-buttons-dt/css/buttons.dataTables.css';

export interface SelectFilter<Row> {
	options: { value: string; label: string }[];
	initial?: string;
	/** Row predicate for a chosen option value. */
	test: (value: string, row: Row) => boolean;
}

export interface FilteredTable<Row> {
	api: Api<Row>;
	/** Set a select filter's value (e.g. from a summary chip) and redraw. */
	setSelect: (column: number, value: string) => void;
	getSelect: (column: number) => string | undefined;
}

/**
 * Build a DataTable in `host`. `selects` maps column index -> drop-down
 * filter; every other column gets a text filter.
 */
export function createFilteredTable<Row>(
	host: HTMLElement,
	columnCount: number,
	options: Config,
	selects: Record<number, SelectFilter<Row>> = {},
): FilteredTable<Row> {
	const el = document.createElement('table');
	el.className = 'display compact stripe hover';
	el.style.width = '100%';
	const head = el.createTHead();
	const titles = head.insertRow();
	const filters = head.insertRow();
	filters.className = 'filters';
	for (let i = 0; i < columnCount; i++) {
		titles.appendChild(document.createElement('th'));
		const th = document.createElement('th');
		th.className = 'dt-orderable-none';
		filters.appendChild(th);
	}
	host.replaceChildren(el);

	const selectEls = new Map<number, HTMLSelectElement>();
	const api = new DataTable<Row>(el, {
		titleRow: 0, // titles in the first header row; the second holds the filters
		autoWidth: false, // no scrollX: see style.css (one table in a scrolling cell)
		...options,
	});

	const cells = el.querySelectorAll<HTMLTableCellElement>('thead tr.filters th');
	api.columns().every(function (idx) {
		const cell = cells[idx];
		// Typing or clicking in a filter must not sort the column.
		for (const ev of ['click', 'keydown', 'mousedown']) cell.addEventListener(ev, (e) => e.stopPropagation());
		const sel = selects[idx];
		if (sel) {
			const select = document.createElement('select');
			for (const o of sel.options) select.add(new Option(o.label, o.value));
			const apply = () => {
				const v = select.value;
				this.search((_d: string | null, row: Row) => sel.test(v, row)).draw();
			};
			select.addEventListener('change', apply);
			cell.replaceChildren(select);
			selectEls.set(idx, select);
			if (sel.initial !== undefined) {
				select.value = sel.initial;
				apply();
			}
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

	return {
		api,
		getSelect(column) {
			return selectEls.get(column)?.value;
		},
		setSelect(column, value) {
			const select = selectEls.get(column);
			if (!select) return;
			select.value = value;
			select.dispatchEvent(new Event('change'));
		},
	};
}

/** Standard toolbar layout ('buttons' is a feature added by the Buttons extension). */
export const TOOLBAR_LAYOUT = {
	topStart: ['pageLength', 'buttons'],
	topEnd: 'search',
} as unknown as Config['layout'];
