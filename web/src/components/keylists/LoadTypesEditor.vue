<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { PHASES, RATING_UNITS, type LoadType, type LoadTypeField, type LoadTypeForm, loadTypeProblems } from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import HistoryButton from '../audit/HistoryButton.vue';
import AppModal from '../common/AppModal.vue';

// Load types: a grid of every row; a row is added or edited in a form and saved from there.
const kl = useKeyLists();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<LoadType> | null = null;
const items = computed(() => kl.loadTypes?.items ?? []);

type Kind = 'text' | 'choice' | 'whole' | 'decimal' | 'yesno';
interface Col { field: LoadTypeField; label: string; kind: Kind; required?: boolean; options?: readonly string[]; hint?: string }
const COLS: Col[] = [
	{ field: 'code', label: 'Code', kind: 'text', required: true },
	{ field: 'name', label: 'Name', kind: 'text', required: true },
	{ field: 'rating_unit', label: 'kW or Amps', kind: 'choice', required: true, options: RATING_UNITS },
	{ field: 'voltage', label: 'Voltage', kind: 'whole', required: true, hint: 'Whole number, e.g. 415' },
	{ field: 'phases', label: 'Phases', kind: 'choice', required: true, options: PHASES },
	{ field: 'from_value', label: 'From value', kind: 'decimal', hint: 'Number' },
	{ field: 'to_value', label: 'To value', kind: 'decimal', hint: 'Number' },
	{ field: 'std_drg', label: 'STD Drg', kind: 'text' },
	{ field: 'bucket_type', label: 'Bucket type', kind: 'text' },
	{ field: 'load_type', label: 'Load type', kind: 'text' },
	{ field: 'field_options', label: 'Field options', kind: 'text' },
	{ field: 'load_qty', label: 'Load qty', kind: 'whole', hint: 'Whole number' },
	{ field: 'multi_load', label: 'Multi load', kind: 'yesno' },
];

function build() {
	if (!host.value || !kl.loadTypes) return;
	table?.api.destroy();
	const columns = COLS.map((c): ColumnsConfig => ({
		title: escapeHtml(c.label) + (c.required ? ' <span class="req" title="Required">*</span>' : ''),
		data: (row: LoadType) => row[c.field] ?? null,
		className: c.kind === 'whole' || c.kind === 'decimal' ? 'dt-right' : c.kind === 'yesno' ? 'center' : c.field === 'code' ? 'key-col' : '',
		render: (v: string | number | boolean | null, type: string) => {
			if (c.kind === 'yesno') return type === 'display' ? (v ? '<span class="yes">✓</span>' : '<span class="no">✗</span>') : v ? 'Yes' : 'No';
			if (v === null || v === '') return '';
			if (type === 'sort' || type === 'type') return c.kind === 'whole' || c.kind === 'decimal' ? Number(v) : String(v).toLowerCase();
			return type === 'display' ? escapeHtml(String(v)) : String(v);
		},
	}));
	const selects: Record<number, SelectFilter<LoadType>> = {};
	COLS.forEach((c, i) => {
		if (c.kind === 'choice') {
			selects[i] = {
				options: [{ value: '', label: 'All' }, ...c.options!.map((o) => ({ value: o, label: o }))],
				test: (v, r) => v === '' || r[c.field] === v,
			};
		} else if (c.kind === 'yesno') {
			selects[i] = {
				options: [{ value: '', label: 'All' }, { value: 'y', label: 'Yes' }, { value: 'n', label: 'No' }],
				test: (v, r) => v === '' || r.multi_load === (v === 'y'),
			};
		}
	});
	table = createFilteredTable<LoadType>(host.value, columns.length, {
		data: items.value,
		columns,
		order: [[0, 'asc']],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible' }, filename: 'Load Types' },
		],
		language: { search: 'Search all:', emptyTable: 'No load types yet. Use "Add load type".' },
	}, selects);
}

// -- the form ---------------------------------------------------------------------------
const editing = ref<{ isNew: boolean; form: LoadTypeForm } | null>(null);
const formErrors = ref<Partial<Record<LoadTypeField, string>>>({});
const text = (v: string | number | null | undefined) => (v === null || v === undefined ? '' : String(v));

function open(row: LoadType | null) {
	formErrors.value = {};
	kl.error = null;
	editing.value = {
		isNew: !row,
		form: {
			id: row?.id ?? newId(), code: row?.code ?? '', name: row?.name ?? '', rating_unit: row?.rating_unit ?? '',
			voltage: text(row?.voltage), phases: row?.phases ?? '', from_value: text(row?.from_value), to_value: text(row?.to_value),
			std_drg: row?.std_drg ?? '', bucket_type: row?.bucket_type ?? '', load_type: row?.load_type ?? '',
			field_options: row?.field_options ?? '', multi_load: row?.multi_load ?? false, load_qty: text(row?.load_qty),
		},
	};
}

function onClick(e: MouseEvent) {
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as LoadType | undefined;
	if (row) open(row);
}

async function save(addAnother = false) {
	const e = editing.value;
	if (!e) return;
	formErrors.value = loadTypeProblems(e.form, items.value.filter((r) => r.id !== e.form.id));
	if (Object.keys(formErrors.value).length) return;
	if (!(await kl.saveLoadType(e.form))) {
		// The engine names problems as "<row id>.<field>"; show this row's beside its inputs.
		const mine: Partial<Record<LoadTypeField, string>> = {};
		for (const [k, msg] of Object.entries(kl.fieldErrors)) {
			if (k.startsWith(`${e.form.id}.`)) mine[k.slice(e.form.id.length + 1) as LoadTypeField] = msg;
		}
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
	if (!e || e.isNew || !confirm(`Delete the load type "${e.form.code}"?`)) return;
	if (await kl.deleteLoadType(e.form.id)) editing.value = null;
}

watch(() => [host.value, kl.loadTypes], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-loads">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Load Types</h2>
			<span class="hint small">{{ items.length }} load type(s). Click a row to edit or delete it.</span>
			<span class="spacer" />
			<HistoryButton entity="load_types" record-id="load-types" label="Load Types" />
			<button type="button" @click="open(null)">Add load type</button>
		</div>
		<p v-if="kl.error && !editing" class="error">{{ kl.error }}</p>
		<div class="results mel-grid">
			<div ref="host" class="result-table ref-rows" @click="onClick" />
		</div>

		<AppModal :open="!!editing" :title="editing?.isNew ? 'Add load type' : 'Edit load type'" @close="close">
			<form v-if="editing" class="form-grid two-col" @submit.prevent="save()">
				<label v-for="c in COLS" :key="c.field" class="field" :class="{ check: c.kind === 'yesno' }">
					<template v-if="c.kind === 'yesno'">
						<input v-model="editing.form.multi_load" type="checkbox" /><span>{{ c.label }}</span>
					</template>
					<template v-else>
						<span>{{ c.label }}<span v-if="c.required" class="req"> *</span></span>
						<select v-if="c.kind === 'choice'" v-model="editing.form[c.field]" :class="{ invalid: formErrors[c.field] }">
							<option value="">—</option>
							<option v-for="o in c.options" :key="o" :value="o">{{ o }}</option>
						</select>
						<input v-else v-model="(editing.form[c.field] as string)" type="text" :placeholder="c.hint"
							:inputmode="c.kind === 'whole' ? 'numeric' : c.kind === 'decimal' ? 'decimal' : undefined"
							:class="{ invalid: formErrors[c.field] }" />
					</template>
					<span v-if="formErrors[c.field]" class="warn small">{{ formErrors[c.field] }}</span>
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
