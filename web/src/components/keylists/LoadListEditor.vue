<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { computed, onBeforeUnmount, ref, toRaw, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import type { Allocation, LoadListChoice, LoadListRow } from '../../lib/keyListTypes';
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
		{ title: 'Key', data: 'key', className: 'key-col', render: (t: string, type: string) => (type === 'display' ? escapeHtml(t) : t) },
		allocColumn('plant_area', 'Plant area'),
		allocColumn('load_type', 'Load type'),
		...v.fields.map((f): ColumnsConfig => ({
			title: escapeHtml(LOAD_FIELD_LABELS[f] ?? f),
			data: (row: LoadListRow) => row.values[f] ?? null,
			className: typeof v.rows.find((r) => r.values[f] != null)?.values[f] === 'number' ? 'dt-right' : '',
			render: (x: string | number | boolean | null, type: string) => {
				if (x === null || x === undefined) return '';
				if (typeof x === 'boolean') return type === 'display' ? (x ? '<span class="yes">✓</span>' : '') : x ? 'Yes' : 'No';
				if (type === 'sort' || type === 'type') return typeof x === 'number' ? x : String(x).toLowerCase();
				return type === 'display' ? escapeHtml(String(x)) : String(x);
			},
		})),
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
		3: allocFilter('plant_area'),
		4: allocFilter('load_type'),
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
	const sel = e.target as HTMLSelectElement;
	if (!sel.classList.contains('alloc')) return;
	const row = toRaw(view.value!.rows)[Number(sel.dataset.row)];
	const kind = sel.dataset.kind as Kind;
	if (!row) return;
	const saved = await kl.allocate([row], { [`${kind}_id`]: sel.value || null } as Allocation);
	if (saved) {
		merge(saved);
		kl.message = `Saved ${row.values.tag ?? row.key}`;
	} else {
		table?.api.rows().invalidate('data').draw(false); // show what is saved
	}
}

// -- set an allocation for every row the filters show ---------------------------------------
const bulk = ref<{ kind: Kind; value: string; rows: LoadListRow[] } | null>(null);

function openBulk(kind: Kind) {
	if (!table) return;
	const rows = table.api.rows({ search: 'applied' }).data().toArray() as LoadListRow[];
	bulk.value = { kind, value: '', rows };
}

async function applyBulk() {
	const b = bulk.value;
	if (!b || !b.rows.length) return;
	const saved = await kl.allocate(b.rows, { [`${b.kind}_id`]: b.value || null } as Allocation);
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
			</span>
			<span class="spacer" />
			<span v-if="kl.message" class="saved">✓ {{ kl.message }}</span>
			<button type="button" class="secondary" :disabled="kl.busy" title="Read the imports again" @click="kl.loadLoadList()">Refresh</button>
		</div>
		<p v-if="kl.error && !bulk" class="error">{{ kl.error }}</p>
		<p class="hint small">
			The rows of every MEL and EEL import (latest file, saved rules and mapping). Only the plant area and load type are edited
			here, and each is saved as soon as you choose it. <em>Italic</em> ones were filled in automatically because the import's
			area or load type equals a plant area's tag number or a load type's code.
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
			</div>
			<div ref="host" class="result-table" @change="onChange" />
		</div>

		<AppModal :open="!!bulk" :title="bulk?.kind === 'plant_area' ? 'Set plant area' : 'Set load type'" @close="bulk = null">
			<template v-if="bulk">
				<p>
					This sets the {{ bulk.kind === 'plant_area' ? 'plant area' : 'load type' }} of the
					<strong>{{ bulk.rows.length }}</strong> row(s) the filters show, replacing what they have now.
				</p>
				<label class="field">
					<span>{{ bulk.kind === 'plant_area' ? 'Plant area' : 'Load type' }}</span>
					<select v-model="bulk.value">
						<option value="">— not allocated —</option>
						<option v-for="c in choices(bulk.kind)" :key="c.id" :value="c.id">{{ '   '.repeat(c.depth) }}{{ c.label }}</option>
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
