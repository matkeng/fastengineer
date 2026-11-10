<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import type { CableType, CableTypeForm } from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import HistoryButton from '../audit/HistoryButton.vue';
import AppModal from '../common/AppModal.vue';

// Cable Types: a grid of every row (a project starts with a default set); a row is added or
// edited in a form and saved from there.
const kl = useKeyLists();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<CableType> | null = null;
const items = computed(() => kl.cableTypes?.items ?? []);

type TextField = 'code' | 'application' | 'type' | 'cores' | 'diameter' | 'voltage' | 'description';
const COLS: { field: TextField | 'sort'; title: string; filter?: 'select'; hint?: string }[] = [
	{ field: 'sort', title: 'Sort', hint: 'Whole number: the order in the list' },
	{ field: 'code', title: 'Code' },
	{ field: 'application', title: 'Application', filter: 'select', hint: 'e.g. AC_415V, DC_24V, Earth' },
	{ field: 'type', title: 'Type', filter: 'select', hint: 'e.g. Power, Control, VSD' },
	{ field: 'cores', title: 'Cores', hint: 'e.g. 3C+E, 4PR' },
	{ field: 'diameter', title: 'Diameter', hint: 'e.g. 2.5' },
	{ field: 'voltage', title: 'Voltage', filter: 'select', hint: 'e.g. 0.6/1kV' },
	{ field: 'description', title: 'Desc' },
];
const distinct = (f: TextField) => [...new Set(items.value.map((r) => r[f]).filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

function build() {
	if (!host.value || !kl.cableTypes) return;
	table?.api.destroy();
	const columns = COLS.map((c): ColumnsConfig => ({
		title: escapeHtml(c.title) + (c.field === 'code' ? ' <span class="req" title="Required">*</span>' : ''),
		data: (r: CableType) => r[c.field] ?? null,
		className: c.field === 'sort' ? 'dt-right' : c.field === 'code' ? 'key-col' : '',
		render: (v: string | number | null, type: string) => {
			if (v === null || v === '') return '';
			if (type === 'sort' || type === 'type') {
				// sizes sort as numbers where they are numbers ("2.5" before "10"), text after
				if (c.field === 'sort') return Number(v);
				if (c.field === 'diameter') return /^[\d.]+$/.test(String(v)) ? String(Number(v) * 1000).padStart(12, '0') : `~${String(v).toLowerCase()}`;
				return String(v).toLowerCase();
			}
			return type === 'display' ? escapeHtml(String(v)) : String(v);
		},
	}));
	const selects: Record<number, SelectFilter<CableType>> = {};
	COLS.forEach((c, i) => {
		if (c.filter !== 'select') return;
		const f = c.field as TextField;
		selects[i] = {
			options: [{ value: '', label: 'All' }, ...distinct(f).map((v) => ({ value: v, label: v }))],
			test: (v, r) => v === '' || r[f] === v,
		};
	});
	table = createFilteredTable<CableType>(host.value, columns.length, {
		data: items.value,
		columns,
		order: [[0, 'asc']],
		pageLength: 100,
		lengthMenu: [50, 100, 250, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: 'Cable Types' },
		],
		language: { search: 'Search all:', emptyTable: 'No cable types. Use "Add cable type" or "Add missing defaults".' },
	}, selects);
}

// -- the form ---------------------------------------------------------------------------
const editing = ref<{ isNew: boolean; form: CableTypeForm } | null>(null);
const formErrors = ref<Record<string, string>>({});
const key = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');

function open(row: CableType | null) {
	formErrors.value = {};
	kl.error = null;
	const next = Math.max(0, ...items.value.map((r) => r.sort ?? 0)) + 1;
	editing.value = {
		isNew: !row,
		form: row ? { ...row, sort: row.sort == null ? '' : String(row.sort) }
			: { id: newId(), code: '', application: '', type: '', cores: '', diameter: '', voltage: '', description: '', sort: String(next) },
	};
}

function onClick(e: MouseEvent) {
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as CableType | undefined;
	if (row) open(row);
}

/** The code the other fields make, e.g. "AC_415V - Power - 3C+E - 2.5". */
const suggested = computed(() => {
	const f = editing.value?.form;
	return f ? [f.application, f.type, f.cores, f.diameter].map((s) => s.trim()).filter(Boolean).join(' - ') : '';
});

async function save(addAnother = false) {
	const e = editing.value;
	if (!e) return;
	const errors: Record<string, string> = {};
	if (!key(e.form.code)) errors.code = 'Code is required';
	else if (items.value.some((r) => r.id !== e.form.id && key(r.code) === key(e.form.code))) errors.code = 'Code is used by another cable type';
	if (e.form.sort.trim() && !/^[+-]?\d+$/.test(e.form.sort.trim())) errors.sort = 'Not a whole number';
	formErrors.value = errors;
	if (Object.keys(errors).length) return;
	if (!(await kl.saveCableType(e.form))) {
		const mine: Record<string, string> = {};
		for (const [k, msg] of Object.entries(kl.fieldErrors)) if (k.startsWith(`${e.form.id}.`)) mine[k.slice(e.form.id.length + 1)] = msg;
		formErrors.value = mine;
		return;
	}
	if (addAnother) {
		open(null);
		await nextTick();
		(document.querySelector('dialog.modal[open] input') as HTMLElement | null)?.focus();
	} else editing.value = null;
}

function close() {
	editing.value = null;
	formErrors.value = {};
	kl.error = null;
}

async function remove() {
	const e = editing.value;
	if (!e || e.isNew || !confirm(`Delete the cable type "${e.form.code}"?`)) return;
	if (await kl.deleteCableType(e.form.id)) editing.value = null;
}

async function addDefaults() {
	const n = await kl.addDefaultCableTypes();
	if (n !== undefined) kl.message = n ? `Added ${n} default cable type(s)` : 'All the default cable types are already in the list';
}

watch(() => [host.value, kl.cableTypes], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-codes key-cables">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Cable Types</h2>
			<span class="hint small">{{ items.length }} cable type(s). Click a row to edit or delete it.</span>
			<span class="spacer" />
			<span v-if="kl.message" class="saved">✓ {{ kl.message }}</span>
			<button type="button" class="secondary" :disabled="kl.busy" title="Add back any of the default cable types that are not in the list; nothing else changes" @click="addDefaults">Add missing defaults</button>
			<HistoryButton entity="cable_types" record-id="cable-types" label="Cable Types" />
			<button type="button" @click="open(null)">Add cable type</button>
		</div>
		<p v-if="kl.error && !editing" class="error">{{ kl.error }}</p>
		<div class="results mel-grid">
			<div ref="host" class="result-table ref-rows" @click="onClick" />
		</div>

		<AppModal :open="!!editing" :title="editing?.isNew ? 'Add cable type' : 'Edit cable type'" @close="close">
			<form v-if="editing" class="form-grid two-col" @submit.prevent="save()">
				<label class="field wide">
					<span>Code<span class="req"> *</span></span>
					<span class="row tight">
						<input v-model="editing.form.code" type="text" class="mono" :class="{ invalid: formErrors.code }" />
						<button v-if="suggested && suggested !== editing.form.code.trim()" type="button" class="secondary small"
							:title="`Use ${suggested}`" @click="editing.form.code = suggested">Make from the fields</button>
					</span>
					<span v-if="formErrors.code" class="warn small">{{ formErrors.code }}</span>
				</label>
				<label v-for="c in COLS.filter((x) => x.field !== 'code' && x.field !== 'description')" :key="c.field" class="field">
					<span>{{ c.title }}</span>
					<input v-model="editing.form[c.field]" type="text" :placeholder="c.hint" :class="{ invalid: formErrors[c.field] }" />
					<span v-if="formErrors[c.field]" class="warn small">{{ formErrors[c.field] }}</span>
				</label>
				<label class="field wide">
					<span>Desc</span>
					<input v-model="editing.form.description" type="text" />
				</label>
				<button type="submit" hidden />
			</form>
			<p v-if="kl.error" class="error">{{ kl.error }}</p>
			<template #footer>
				<button v-if="editing && !editing.isNew" type="button" class="secondary" :disabled="kl.busy" @click="remove">Delete</button>
				<span class="spacer" />
				<button type="button" class="secondary" @click="close">Cancel</button>
				<button v-if="editing?.isNew" type="button" class="secondary" :disabled="kl.busy" @click="save(true)">Save and add another</button>
				<button type="button" :disabled="kl.busy" @click="save()">Save</button>
			</template>
		</AppModal>
	</section>
</template>
