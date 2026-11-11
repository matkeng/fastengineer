<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import ListWorkbook from './ListWorkbook.vue';
import LoadFieldsEditor from './LoadFieldsEditor.vue';
import LoadListReset from './LoadListReset.vue';
import { useProjects } from '../../stores/projects';
import type { ColumnsConfig } from 'datatables.net';
import { computed, onBeforeUnmount, ref, toRaw, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import {
	type Allocation, type CableConstruction, type CableDetails, EEL_SOURCE, type LoadListChoice, type LoadListRow, PRIMARY_SUPPLY, cableSummary, rowRef, rowTag,
} from '../../lib/keyListTypes';
import { LOAD_FIELD_LABELS } from '../../lib/melTypes';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import AppModal from '../common/AppModal.vue';

// The Load List: the MEL and EEL imports' rows, read-only, with a plant area and a load
// type allocated to each row. An allocation is saved as soon as it is chosen.
const kl = useKeyLists();
const editingFields = ref(false);
const projects = useProjects();
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
// Rows from the Electrical Equipment List: what is edited here is set there instead.
const fromEel = (r: LoadListRow) => r.recipe_id === EEL_SOURCE;
const eelCell = (text: string) => `<span class="from-eel" title="Set in the Electrical Equipment List">${escapeHtml(text) || '—'}</span>`;
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
			if (fromEel(row)) return eelCell(label);
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
			title: escapeHtml(v.labels.tag ?? 'Tag'), data: (row: LoadListRow) => rowTag(row), className: 'key-col',
			render: (t: string, type: string, row: LoadListRow) => (type === 'display'
				? `<span${t !== row.key ? ` title="Key in the import: ${escapeHtml(row.key)}"` : ''}>${escapeHtml(t)}</span>` : t),
		},
		{
			title: escapeHtml(v.labels.desc ?? 'Description'), data: (row: LoadListRow) => (row.values.desc == null ? '' : String(row.values.desc)), className: 'desc-col',
			render: (t: string, type: string) => (type === 'display' ? `<span title="${escapeHtml(t)}">${escapeHtml(t)}</span>` : t),
		},
		allocColumn('plant_area', 'Plant area'),
		allocColumn('load_type', 'Load type'),
		{
			title: 'Distribution panel', data: (row: LoadListRow) => row.is_panel, className: 'alloc-col center',
			render: (on: boolean, type: string, row: LoadListRow) => {
				if (type !== 'display') return on ? 'Yes' : 'No';
				if (fromEel(row)) return eelCell(on ? '✓' : '');
				const tip = row.is_panel_by === 'auto' ? autoTip : 'Other rows can be supplied from a distribution panel';
				return `<label class="panel-flag${row.is_panel_by === 'auto' ? ' auto' : ''}" title="${tip}"><input type="checkbox" class="alloc-check" data-row="${rows.indexOf(row)}" aria-label="Distribution panel"${on ? ' checked' : ''} /></label>`;
			},
		},
		{
			title: 'Supplied from', data: (row: LoadListRow) => row.supplied_from ?? '', className: 'alloc-col',
			render: (ref: string, type: string, row: LoadListRow) => {
				const label = supplyLabel(ref || null);
				if (type !== 'display') return label;
				if (fromEel(row)) return eelCell(label);
				const own = rowRef(row);
				const options = supplyChoices(own);
				let html = '<option value="">— not set —</option>'
					+ options.map((c) => `<option value="${escapeHtml(c.id)}"${c.id === ref ? ' selected' : ''}>${escapeHtml(c.label)}</option>`).join('');
				if (ref && !options.some((c) => c.id === ref)) html += `<option value="${escapeHtml(ref)}" selected>${escapeHtml(label)}</option>`;
				const cls = `alloc${row.supplied_from_by === 'auto' ? ' auto' : ''}${label.startsWith('⚠') ? ' broken' : ''}`;
				return `<select class="${cls}" data-kind="supplied_from" data-row="${rows.indexOf(row)}" aria-label="Supplied from" title="${row.supplied_from_by === 'auto' ? autoTip : ''}">${html}</select>`;
			},
		},
		{
			// The power cable's details, typed in here for any row; click to edit (see onClick).
			title: 'Cable', data: (row: LoadListRow) => cableSummary(row), className: 'alloc-col cable-col',
			render: (t: string, type: string, row: LoadListRow) => (type !== 'display' ? t
				: `<button type="button" class="link cable-edit${t ? '' : ' none'}" data-cable="${rows.indexOf(row)}" title="Cable length, size, insulation, parallel cables">${escapeHtml(t) || 'Set…'}</button>`),
		},
		...v.fields.filter((f) => f !== 'tag' && f !== 'desc').map((f): ColumnsConfig => ({
			// The import's own text for what is edited here is marked, so the two can't be mixed up.
			title: escapeHtml(v.labels[f] ?? LOAD_FIELD_LABELS[f] ?? f) + (FROM_IMPORT.has(f) ? ' (import)' : ''),
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

// -- the power cable's details: one row (click its Cable cell) or every row the filters show --
type CableField = keyof CableDetails;
const CABLE_FIELDS: CableField[] = ['cable_construction', 'cable_parallel', 'cable_size', 'cable_insulation', 'earth_size', 'cable_length'];
const cable = ref<{ rows: LoadListRow[]; bulk: boolean; set: Record<CableField, boolean>;
	form: { cable_length: string; cable_construction: CableConstruction; cable_parallel: string; cable_insulation: string; cable_size: string; earth_size: string } } | null>(null);
const cableErrors = computed(() => kl.fieldErrors as Partial<Record<CableField, string>>);

function openCable(rows: LoadListRow[], bulk: boolean) {
	const r = bulk ? null : rows[0];
	kl.error = null;
	kl.fieldErrors = {};
	cable.value = {
		rows, bulk, set: Object.fromEntries(CABLE_FIELDS.map((f) => [f, !bulk])) as Record<CableField, boolean>,
		form: {
			cable_length: r?.cable_length == null ? '' : String(r.cable_length), cable_construction: r?.cable_construction ?? 'Multicore',
			cable_parallel: String(r?.cable_parallel ?? 1), cable_insulation: r?.cable_insulation ?? '', cable_size: r?.cable_size ?? '',
			earth_size: r?.earth_size ?? '',
		},
	};
}

function onClick(e: MouseEvent) {
	const el = (e.target as HTMLElement).closest<HTMLElement>('[data-cable]');
	const row = el ? toRaw(view.value!.rows)[Number(el.dataset.cable)] : null;
	if (row) openCable([row], false);
}

async function applyCable() {
	const c = cable.value;
	if (!c || !c.rows.length) return;
	const f = c.form;
	// a number input's model is a number once typed in
	const number = (t: string | number) => (String(t).trim() === '' ? null : Number(String(t).replace(/,/g, '')));
	const all: CableDetails = {
		cable_length: number(f.cable_length), cable_construction: f.cable_construction, cable_parallel: number(f.cable_parallel),
		cable_insulation: f.cable_insulation, cable_size: f.cable_size, earth_size: f.cable_construction === 'Single core' ? f.earth_size : '',
	};
	if (Number.isNaN(all.cable_length) || Number.isNaN(all.cable_parallel) || (all.cable_parallel != null && !Number.isInteger(all.cable_parallel))) {
		kl.error = 'Length is a number and parallel cables a whole number.';
		return;
	}
	const change = Object.fromEntries(CABLE_FIELDS.filter((k) => c.set[k]).map((k) => [k, all[k]])) as Allocation;
	if (!Object.keys(change).length) {
		kl.error = 'Tick what to change.';
		return;
	}
	const saved = await kl.allocate(c.rows, change);
	if (saved) {
		merge(saved);
		kl.message = c.bulk ? `Saved ${saved.length} row(s)` : `Saved ${rowTag(c.rows[0])}`;
		cable.value = null;
	}
}

function openBulkCable() {
	if (table) openCable(table.api.rows({ search: 'applied' }).data().toArray() as LoadListRow[], true);
}

// -- set an allocation for every row the filters show ---------------------------------------
const bulk = ref<{ kind: SelectKind; value: string; rows: LoadListRow[]; skipped: number } | null>(null);
const BULK_TITLE: Record<SelectKind, string> = { plant_area: 'plant area', load_type: 'load type', supplied_from: 'supplied from' };

function openBulk(kind: SelectKind) {
	if (!table) return;
	const shown = table.api.rows({ search: 'applied' }).data().toArray() as LoadListRow[];
	const rows = shown.filter((r) => !fromEel(r));
	bulk.value = { kind, value: '', rows, skipped: shown.length - rows.length };
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
			<span class="kind tree">Master list</span>
			<h2 class="key-title">Project Master Load List</h2>
			<span v-if="view" class="hint small">
				{{ counts.active }} row(s)<template v-if="counts.deleted"> · {{ counts.deleted }} deleted</template>
				· <span :class="{ warnText: counts.noArea }">{{ counts.noArea }} without a plant area</span>
				· <span :class="{ warnText: counts.noType }">{{ counts.noType }} without a load type</span>
				· <span :class="{ warnText: counts.noSupply }">{{ counts.noSupply }} without a supply</span>
				· {{ counts.panels }} distribution panel(s)
			</span>
			<span class="spacer" />
			<span v-if="kl.message" class="saved">✓ {{ kl.message }}</span>
			<button type="button" class="secondary" title="Rename, add, delete or reorder the fields imports map onto and this list shows" @click="editingFields = true">Edit fields…</button>
			<ListWorkbook list-id="load-list" name="Load List" />
			<LoadListReset :project="projects.current?.name ?? 'this project'" />
			<button type="button" class="secondary" :disabled="kl.busy" title="Read the imports again" @click="kl.loadLoadList()">Refresh</button>
		</div>
		<p v-if="kl.error && !bulk" class="error">{{ kl.error }}</p>
		<p class="hint small">
			The rows of every MEL and EEL import (latest file, saved rules and mapping) and of the Electrical Equipment List
			(whose plant area, load type, panel and supply are set in that list). The plant area, load type, distribution
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
				<button type="button" class="secondary small" :disabled="kl.busy" @click="openBulkCable">Set cable details…</button>
			</div>
			<div ref="host" class="result-table" @change="onChange" @click="onClick" />
		</div>

		<AppModal :open="!!bulk" :title="`Set ${bulk ? BULK_TITLE[bulk.kind] : ''}`" @close="bulk = null">
			<template v-if="bulk">
				<p>
					This sets the {{ BULK_TITLE[bulk.kind] }} of the
					<strong>{{ bulk.rows.length }}</strong> row(s) the filters show, replacing what they have now.
				</p>
				<p v-if="bulk.skipped" class="hint">
					{{ bulk.skipped }} row(s) from the Electrical Equipment List are left out: change those in that list.
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

		<AppModal class="cable-form" :open="!!cable" :title="cable?.bulk ? 'Set cable details' : `Power cable of ${cable ? rowTag(cable.rows[0]) : ''}`" @close="cable = null">
			<template v-if="cable">
				<p v-if="cable.bulk">
					This sets the ticked details for the <strong>{{ cable.rows.length }}</strong> row(s) the filters show, replacing what they have now.
				</p>
				<p v-else class="hint small">
					Typed in here (cable sizing is done outside this app). The cable schedule uses these to find the cable in Cable Types.
				</p>
				<form class="form-grid cable-grid" @submit.prevent="applyCable">
					<label class="field"><span><input v-if="cable.bulk" v-model="cable.set.cable_construction" type="checkbox" /> Power cable</span>
						<select v-model="cable.form.cable_construction" :disabled="!cable.set.cable_construction">
							<option>Multicore</option><option>Single core</option>
						</select>
						<span v-if="cableErrors.cable_construction" class="warn small">{{ cableErrors.cable_construction }}</span></label>
					<label class="field"><span><input v-if="cable.bulk" v-model="cable.set.cable_parallel" type="checkbox" /> Parallel cables</span>
						<input v-model="cable.form.cable_parallel" type="number" min="1" step="1" :disabled="!cable.set.cable_parallel" :class="{ invalid: cableErrors.cable_parallel }" />
						<span class="hint small">{{ cable.form.cable_construction === 'Single core' ? 'Sets of single cores per phase' : 'Multicore cables run in parallel' }}</span>
						<span v-if="cableErrors.cable_parallel" class="warn small">{{ cableErrors.cable_parallel }}</span></label>
					<label class="field"><span><input v-if="cable.bulk" v-model="cable.set.cable_size" type="checkbox" /> Core size (mm²)</span>
						<select v-model="cable.form.cable_size" :disabled="!cable.set.cable_size" :class="{ invalid: cableErrors.cable_size }">
							<option value="">— not set —</option>
							<option v-for="s in view?.cable_sizes" :key="s" :value="s">{{ s }}</option>
						</select>
						<span v-if="cableErrors.cable_size" class="warn small">{{ cableErrors.cable_size }}</span></label>
					<label class="field"><span><input v-if="cable.bulk" v-model="cable.set.cable_insulation" type="checkbox" /> Insulation</span>
						<select v-model="cable.form.cable_insulation" :disabled="!cable.set.cable_insulation" :class="{ invalid: cableErrors.cable_insulation }">
							<option value="">— not set —</option>
							<option v-for="s in view?.cable_insulations" :key="s" :value="s">{{ s }}</option>
						</select>
						<span v-if="cableErrors.cable_insulation" class="warn small">{{ cableErrors.cable_insulation }}</span></label>
					<label v-if="cable.form.cable_construction === 'Single core'" class="field"><span><input v-if="cable.bulk" v-model="cable.set.earth_size" type="checkbox" /> Earth cable size (mm²)</span>
						<select v-model="cable.form.earth_size" :disabled="!cable.set.earth_size" :class="{ invalid: cableErrors.earth_size }">
							<option value="">— not set —</option>
							<option v-for="s in view?.earth_sizes" :key="s" :value="s">{{ s }}</option>
						</select>
						<span class="hint small">The separate earth cable of a single-core set</span>
						<span v-if="cableErrors.earth_size" class="warn small">{{ cableErrors.earth_size }}</span></label>
					<label class="field"><span><input v-if="cable.bulk" v-model="cable.set.cable_length" type="checkbox" /> Cable length (m)</span>
						<input v-model="cable.form.cable_length" type="text" inputmode="decimal" :disabled="!cable.set.cable_length" :class="{ invalid: cableErrors.cable_length }" />
						<span v-if="cableErrors.cable_length" class="warn small">{{ cableErrors.cable_length }}</span></label>
					<button type="submit" hidden />
				</form>
				<p v-if="kl.error" class="error">{{ kl.error }}</p>
			</template>
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="cable = null">Cancel</button>
				<button type="button" :disabled="kl.busy || !cable?.rows.length" @click="applyCable">{{ cable?.bulk ? `Set ${cable.rows.length} row(s)` : 'Save' }}</button>
			</template>
		</AppModal>
		<LoadFieldsEditor :open="editingFields" @close="editingFields = false" @saved="kl.loadLoadList()" />
	</section>
</template>
