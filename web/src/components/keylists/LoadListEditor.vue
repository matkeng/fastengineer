<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { computed, onBeforeUnmount, ref, toRaw, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { type Allocation, type LoadListChoice, type LoadListRow, PRIMARY_SUPPLY, rowRef, rowTag } from '../../lib/keyListTypes';
import { LOAD_FIELD_LABELS } from '../../lib/melTypes';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import AppModal from '../common/AppModal.vue';

// The Load List: the MEL and EEL imports' rows, read-only, with a plant area and a load
// type allocated to each row. An allocation is saved as soon as it is chosen.
const kl = useKeyLists();
const ui = useUi();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<LoadListRow> | null = null;
const view = computed(() => kl.loadList);
const version = ref(0); // bumped when rows change in place (the grid holds the same objects)

type Kind = 'plant_area' | 'load_type';
const KINDS: { kind: Kind; title: string; empty: string }[] = [
	{ kind: 'plant_area', title: 'Plant area', empty: 'Not allocated' },
	{ kind: 'load_type', title: 'Load type', empty: 'Not allocated' },
];
const choices = (kind: Kind): LoadListChoice[] => (kind === 'plant_area' ? view.value?.plant_areas : view.value?.load_types) ?? [];
type SelectKind = Kind | 'supplied_from';

// Supplied from: the primary supply or one of the list's (active) distribution panels.
function panels(): LoadListRow[] {
	void version.value;
	return (view.value?.rows ?? []).filter((r) => r.is_panel && r.status === 'active')
		.sort((a, b) => rowTag(a).localeCompare(rowTag(b), undefined, { numeric: true }));
}
const panelLabel = (r: LoadListRow) => (r.values.desc ? `${rowTag(r)} – ${r.values.desc}` : rowTag(r));
function supplyLabel(ref: string | null): string {
	if (!ref) return '';
	if (ref === PRIMARY_SUPPLY) return 'Primary Supply';
	const r = view.value?.rows.find((x) => rowRef(x) === ref);
	if (!r) return '⚠ removed row';
	return r.is_panel && r.status === 'active' ? rowTag(r) : `⚠ ${rowTag(r)} (not an active panel)`;
}
/** Bulk and per-row choices; `except` = the row itself (it can't supply itself). */
const supplyChoices = (except?: string): LoadListChoice[] => [
	{ id: PRIMARY_SUPPLY, label: 'Primary Supply', depth: 0 },
	...panels().filter((r) => rowRef(r) !== except).map((r) => ({ id: rowRef(r), label: panelLabel(r), depth: 0 })),
];
const bulkChoices = (kind: SelectKind) => (kind === 'supplied_from' ? supplyChoices() : choices(kind));
const FROM_IMPORT = new Set(['area', 'load_type', 'is_a_loadcentre', 'supplied_from']);
const autoTip = 'Filled in automatically from the import (it follows the import until you choose)';
const labelOf = (kind: Kind, id: string | null) => (id ? choices(kind).find((c) => c.id === id)?.label ?? '⚠ deleted item' : '');

const counts = computed(() => {
	void version.value;
	const rows = view.value?.rows ?? [];
	const active = rows.filter((r) => r.status === 'active');
	return {
		active: active.length,
		deleted: rows.length - active.length,
		noArea: active.filter((r) => !r.plant_area_id).length,
		noType: active.filter((r) => !r.load_type_id).length,
		noSupply: active.filter((r) => !r.supplied_from).length,
		panels: active.filter((r) => r.is_panel).length,
	};
});
const noFile = computed(() => view.value?.sources.filter((s) => !s.has_file) ?? []);

function optionsHtml(kind: Kind): string {
	const indent = (d: number) => '   '.repeat(d);
	return `<option value="">— ${KINDS.find((k) => k.kind === kind)!.empty.toLowerCase()} —</option>`
		+ choices(kind).map((c) => `<option value="${escapeHtml(c.id)}">${indent(c.depth)}${escapeHtml(c.label)}</option>`).join('');
}

function build() {
	if (!host.value || !view.value) return;
	table?.api.destroy();
	table = null;
	const v = view.value;
	const rows = toRaw(v.rows);
	const options = { plant_area: optionsHtml('plant_area'), load_type: optionsHtml('load_type') };

	const allocColumn = (kind: Kind, title: string): ColumnsConfig => ({
		title,
		data: (row: LoadListRow) => row[`${kind}_id`] ?? '',
		className: 'alloc-col',
		render: (id: string, type: string, row: LoadListRow) => {
			const label = labelOf(kind, id || null);
			if (type !== 'display') return label;
			let html = options[kind];
			if (id && !choices(kind).some((c) => c.id === id)) html += `<option value="${escapeHtml(id)}">⚠ deleted item</option>`;
			if (id) html = html.replace(`value="${escapeHtml(id)}"`, `value="${escapeHtml(id)}" selected`);
			const by = row[`${kind}_by`];
			const tip = by === 'auto' ? 'Filled in automatically from the import (it follows the import until you choose)' : by === 'user' ? 'Chosen by a person' : '';
			return `<select class="alloc${by === 'auto' ? ' auto' : ''}" data-kind="${kind}" data-row="${rows.indexOf(row)}" aria-label="${title}" title="${tip}">${html}</select>`;
		},
	});

	const columns: ColumnsConfig[] = [
		{
			title: 'Status', data: 'status', className: 'center',
			render: (s: string, type: string, row: LoadListRow) => {
				if (type !== 'display') return s === 'active' ? 'Active' : 'Deleted';
				return s === 'active' ? '' : `<span class="deleted-tag" title="${escapeHtml(row.deleted_reason)}">Deleted</span>`;
			},
		},
		{ title: 'Source', data: (row: LoadListRow) => `${row.source} (${row.target})`, render: (t: string, type: string) => (type === 'display' ? escapeHtml(t) : t) },
		// What the row is, next to what is allocated to it. The tag is the import's key when no tag is mapped.
		{
			title: 'Tag number', data: (row: LoadListRow) => rowTag(row), className: 'key-col',
			render: (t: string, type: string, row: LoadListRow) => (type === 'display'
				? `<span${t !== row.key ? ` title="Key in the import: ${escapeHtml(row.key)}"` : ''}>${escapeHtml(t)}</span>` : t),
		},
		{
			title: 'Description', data: (row: LoadListRow) => (row.values.desc == null ? '' : String(row.values.desc)), className: 'desc-col',
			render: (t: string, type: string) => (type === 'display' ? `<span title="${escapeHtml(t)}">${escapeHtml(t)}</span>` : t),
		},
		allocColumn('plant_area', 'Plant area'),
		allocColumn('load_type', 'Load type'),
		{
			title: 'Distribution panel', data: (row: LoadListRow) => row.is_panel, className: 'alloc-col center',
			render: (on: boolean, type: string, row: LoadListRow) => {
				if (type !== 'display') return on ? 'Yes' : 'No';
				const tip = row.is_panel_by === 'auto' ? autoTip : 'Other rows can be supplied from a distribution panel';
				return `<label class="panel-flag${row.is_panel_by === 'auto' ? ' auto' : ''}" title="${tip}"><input type="checkbox" class="alloc-check" data-row="${rows.indexOf(row)}" aria-label="Distribution panel"${on ? ' checked' : ''} /></label>`;
			},
		},
		{
			title: 'Supplied from', data: (row: LoadListRow) => row.supplied_from ?? '', className: 'alloc-col',
			render: (ref: string, type: string, row: LoadListRow) => {
				const label = supplyLabel(ref || null);
				if (type !== 'display') return label;
				const own = rowRef(row);
				const options = supplyChoices(own);
				let html = '<option value="">— not set —</option>'
					+ options.map((c) => `<option value="${escapeHtml(c.id)}"${c.id === ref ? ' selected' : ''}>${escapeHtml(c.label)}</option>`).join('');
				if (ref && !options.some((c) => c.id === ref)) html += `<option value="${escapeHtml(ref)}" selected>${escapeHtml(label)}</option>`;
				const cls = `alloc${row.supplied_from_by === 'auto' ? ' auto' : ''}${label.startsWith('⚠') ? ' broken' : ''}`;
				return `<select class="${cls}" data-kind="supplied_from" data-row="${rows.indexOf(row)}" aria-label="Supplied from" title="${row.supplied_from_by === 'auto' ? autoTip : ''}">${html}</select>`;
			},
		},
		...v.fields.filter((f) => f !== 'tag' && f !== 'desc').map((f): ColumnsConfig => ({
			// The import's own text for what is edited here is marked, so the two can't be mixed up.
			title: escapeHtml(LOAD_FIELD_LABELS[f] ?? f) + (FROM_IMPORT.has(f) ? ' (import)' : ''),
			data: (row: LoadListRow) => row.values[f] ?? null,
			className: typeof v.rows.find((r) => r.values[f] != null)?.values[f] === 'number' ? 'dt-right' : '',
			render: (x: string | number | boolean | null, type: string) => {
				if (x === null || x === undefined) return '';
				if (typeof x === 'boolean') return type === 'display' ? (x ? '<span class="yes">✓</span>' : '') : x ? 'Yes' : 'No';
				if (type === 'sort' || type === 'type') return typeof x === 'number' ? x : String(x).toLowerCase();
				return type === 'display' ? escapeHtml(String(x)) : String(x);
			},
		})),
		// The import's key, for when it differs from the tag (hidden; shown with "Columns").
		{ title: 'Key (import)', data: 'key', visible: false, render: (t: string, type: string) => (type === 'display' ? escapeHtml(t) : t) },
	];

	const allocFilter = (kind: Kind): SelectFilter<LoadListRow> => ({
		options: [{ value: '', label: 'All' }, { value: '__none', label: '(not allocated)' }, { value: '__auto', label: '(filled in automatically)' },
			...choices(kind).map((c) => ({ value: c.id, label: c.label }))],
		test: (val, r) => val === '' || (val === '__none' ? !r[`${kind}_id`] : val === '__auto' ? r[`${kind}_by`] === 'auto' : r[`${kind}_id`] === val),
	});
	const selects: Record<number, SelectFilter<LoadListRow>> = {
		0: {
			options: [{ value: '', label: 'All' }, { value: 'active', label: 'Active' }, { value: 'deleted', label: 'Deleted' }],
			test: (val, r) => val === '' || r.status === val,
		},
		1: {
			options: [{ value: '', label: 'All' }, ...v.sources.filter((s) => s.has_file).map((s) => ({ value: s.id, label: `${s.name} (${s.target})` }))],
			test: (val, r) => val === '' || r.recipe_id === val,
		},
		4: allocFilter('plant_area'),
		5: allocFilter('load_type'),
		6: {
			options: [{ value: '', label: 'All' }, { value: 'y', label: 'Panels' }, { value: 'n', label: 'Not panels' }],
			test: (val, r) => val === '' || r.is_panel === (val === 'y'),
		},
		// 7 (supplied from): a text filter, so it matches a panel's tag, "Primary Supply" or "⚠".
	};

	table = createFilteredTable<LoadListRow>(host.value, columns.length, {
		data: rows,
		columns,
		order: [[1, 'asc'], [2, 'asc']],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: 'Load List' },
		],
		language: { search: 'Search all:', emptyTable: 'No rows: the MEL and EEL imports have no rows yet.' },
		createdRow: (tr: HTMLTableRowElement, row: unknown) => {
			if ((row as LoadListRow).status === 'deleted') tr.classList.add('row-deleted');
		},
	}, selects);
}

/** Put saved rows back into the grid (same objects, so filters and the page stay as they are). */
function merge(saved: LoadListRow[]) {
	const rows = toRaw(view.value!.rows);
	for (const s of saved) {
		const r = rows.find((x) => x.recipe_id === s.recipe_id && x.key === s.key);
		if (r) Object.assign(r, s);
	}
	table?.api.rows().invalidate('data').draw(false);
	version.value++;
}

async function onChange(e: Event) {
	const el = e.target as HTMLSelectElement | HTMLInputElement;
	let change: Allocation;
	if (el.classList.contains('alloc-check')) change = { is_panel: (el as HTMLInputElement).checked };
	else if (el.classList.contains('alloc')) {
		const kind = el.dataset.kind as SelectKind;
		change = kind === 'supplied_from' ? { supplied_from: el.value || null } : { [`${kind}_id`]: el.value || null };
	} else return;
	const row = toRaw(view.value!.rows)[Number(el.dataset.row)];
	if (!row) return;
	const saved = await kl.allocate([row], change);
	if (saved) {
		merge(saved);
		kl.message = `Saved ${row.values.tag ?? row.key}`;
	} else {
		table?.api.rows().invalidate('data').draw(false); // show what is saved
	}
}

// -- set an allocation for every row the filters show ---------------------------------------
const bulk = ref<{ kind: SelectKind; value: string; rows: LoadListRow[] } | null>(null);
const BULK_TITLE: Record<SelectKind, string> = { plant_area: 'plant area', load_type: 'load type', supplied_from: 'supplied from' };

function openBulk(kind: SelectKind) {
	if (!table) return;
	const rows = table.api.rows({ search: 'applied' }).data().toArray() as LoadListRow[];
	bulk.value = { kind, value: '', rows };
}

async function applyBulk() {
	const b = bulk.value;
	if (!b || !b.rows.length) return;
	const change: Allocation = b.kind === 'supplied_from' ? { supplied_from: b.value || null } : { [`${b.kind}_id`]: b.value || null };
	const saved = await kl.allocate(b.rows, change);
	if (saved) {
		merge(saved);
		kl.message = `Saved ${saved.length} row(s)`;
		bulk.value = null;
	}
}

watch(() => [host.value, kl.loadList], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-loadlist">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Load List</h2>
			<span v-if="view" class="hint small">
				{{ counts.active }} row(s)<template v-if="counts.deleted"> · {{ counts.deleted }} deleted</template>
				· <span :class="{ warnText: counts.noArea }">{{ counts.noArea }} without a plant area</span>
				· <span :class="{ warnText: counts.noType }">{{ counts.noType }} without a load type</span>
				· <span :class="{ warnText: counts.noSupply }">{{ counts.noSupply }} without a supply</span>
				· {{ counts.panels }} distribution panel(s)
			</span>
			<span class="spacer" />
			<span v-if="kl.message" class="saved">✓ {{ kl.message }}</span>
			<button type="button" class="secondary" :disabled="kl.busy" title="Read the imports again" @click="kl.loadLoadList()">Refresh</button>
		</div>
		<p v-if="kl.error && !bulk" class="error">{{ kl.error }}</p>
		<p class="hint small">
			The rows of every MEL and EEL import (latest file, saved rules and mapping). The plant area, load type, distribution
			panel and supplied from are edited here, each saved as soon as you choose it. <em>Italic</em> ones were filled in
			automatically from the import: its area / load type equals a plant area's tag number / a load type's code, its
			"is a load centre" marks a panel, and its "supplied from" equals a panel's tag.
		</p>
		<div v-if="view && (view.warnings.length || noFile.length)" class="chips">
			<span v-for="s in noFile" :key="s.id" class="chip warn-chip">⚠ {{ s.name }} ({{ s.target }}) has no file yet</span>
			<span v-for="w in view.warnings" :key="w" class="chip warn-chip">⚠ {{ w }}</span>
		</div>

		<section v-if="view && !view.sources.length && !view.rows.length" class="ref-empty">
			<p>There are no MEL or EEL imports in this project yet. The Load List is made from them.</p>
			<button type="button" @click="ui.go('mel')">Open List import</button>
		</section>
		<p v-else-if="!view" class="hint">Building the load list from the imports…</p>
		<div v-else class="results mel-grid">
			<div class="row">
				<span class="hint small">For every row the filters show:</span>
				<button type="button" class="secondary small" :disabled="kl.busy" @click="openBulk('plant_area')">Set plant area…</button>
				<button type="button" class="secondary small" :disabled="kl.busy" @click="openBulk('load_type')">Set load type…</button>
				<button type="button" class="secondary small" :disabled="kl.busy" @click="openBulk('supplied_from')">Set supplied from…</button>
			</div>
			<div ref="host" class="result-table" @change="onChange" />
		</div>

		<AppModal :open="!!bulk" :title="`Set ${bulk ? BULK_TITLE[bulk.kind] : ''}`" @close="bulk = null">
			<template v-if="bulk">
				<p>
					This sets the {{ BULK_TITLE[bulk.kind] }} of the
					<strong>{{ bulk.rows.length }}</strong> row(s) the filters show, replacing what they have now.
				</p>
				<label class="field">
					<span>{{ BULK_TITLE[bulk.kind][0].toUpperCase() + BULK_TITLE[bulk.kind].slice(1) }}</span>
					<select v-model="bulk.value">
						<option value="">{{ bulk.kind === 'supplied_from' ? '— not set —' : '— not allocated —' }}</option>
						<option v-for="c in bulkChoices(bulk.kind)" :key="c.id" :value="c.id">{{ '   '.repeat(c.depth) }}{{ c.label }}</option>
					</select>
				</label>
				<p v-if="kl.error" class="error">{{ kl.error }}</p>
			</template>
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="bulk = null">Cancel</button>
				<button type="button" :disabled="kl.busy || !bulk?.rows.length" @click="applyBulk">Set {{ bulk?.rows.length }} row(s)</button>
			</template>
		</AppModal>
	</section>
</template>
