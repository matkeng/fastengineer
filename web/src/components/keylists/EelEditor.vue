<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import ListWorkbook from './ListWorkbook.vue';
import type { ColumnsConfig } from 'datatables.net';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { EEL_SOURCE, type EelChoice, type EelForm, type EelItem, PHASES, RATING_UNITS, eelProblems } from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import HistoryButton from '../audit/HistoryButton.vue';
import ListUndoButtons from './ListUndoButtons.vue';
import AppModal from '../common/AppModal.vue';

// The Electrical Equipment List: a grid of every item; an item is added or edited in a form
// and saved from there. Each item is also a row of the Load List.
const kl = useKeyLists();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<EelItem> | null = null;
const view = computed(() => kl.eel);
const items = computed(() => view.value?.items ?? []);
const NB = '   ';

type Ref = 'equipment_code_id' | 'plant_area_id' | 'vendor_package_id' | 'load_type_id' | 'supplied_from'
	| 'supplied_by_id' | 'installed_by_id' | 'terminated_by_id';
const CHOICES: Record<Ref, 'equipment_codes' | 'plant_areas' | 'packages' | 'load_types' | 'supplies'> = {
	equipment_code_id: 'equipment_codes', plant_area_id: 'plant_areas', vendor_package_id: 'packages', load_type_id: 'load_types',
	supplied_from: 'supplies', supplied_by_id: 'packages', installed_by_id: 'packages', terminated_by_id: 'packages',
};
const choices = (f: Ref): EelChoice[] => view.value?.choices[CHOICES[f]] ?? [];
/** The text shown for a reference (the plant area / package / … label without its description). */
function labelOf(f: Ref, id: string | null, full = false): string {
	if (!id) return '';
	const c = choices(f).find((x) => x.id === id);
	if (!c) return '⚠ removed';
	return full || f === 'supplied_from' ? c.label : c.label.split(' – ')[0];
}

interface Col { field: keyof EelItem; title: string; ref?: Ref; filter?: 'select'; num?: boolean }
const COLS: Col[] = [
	{ field: 'tag', title: 'Tag number' },
	{ field: 'description', title: 'Description' },
	{ field: 'equipment_code_id', title: 'Equipment type', ref: 'equipment_code_id', filter: 'select' },
	{ field: 'plant_area_id', title: 'Plant area', ref: 'plant_area_id', filter: 'select' },
	{ field: 'vendor_package_id', title: 'Vendor package', ref: 'vendor_package_id', filter: 'select' },
	{ field: 'load_type_id', title: 'Load type', ref: 'load_type_id', filter: 'select' },
	{ field: 'rating', title: 'Rating', num: true },
	{ field: 'rating_unit', title: 'kW or Amps', filter: 'select' },
	{ field: 'voltage', title: 'Voltage', num: true },
	{ field: 'phases', title: 'Phases', filter: 'select' },
	{ field: 'is_panel', title: 'Distribution panel', filter: 'select' },
	{ field: 'supplied_from', title: 'Supplied from', ref: 'supplied_from' },
	{ field: 'manufacturer', title: 'Manufacturer' },
	{ field: 'model_number', title: 'Model number' },
	{ field: 'supplied_by_id', title: 'Supplied by', ref: 'supplied_by_id', filter: 'select' },
	{ field: 'installed_by_id', title: 'Installed by', ref: 'installed_by_id', filter: 'select' },
	{ field: 'terminated_by_id', title: 'Terminated by', ref: 'terminated_by_id', filter: 'select' },
];

function build() {
	if (!host.value || !view.value) return;
	table?.api.destroy();
	const clashes = view.value.clashes;
	const columns = COLS.map((c): ColumnsConfig => ({
		title: escapeHtml(c.title),
		data: (r: EelItem) => r[c.field] ?? null,
		className: c.num ? 'dt-right' : c.field === 'tag' ? 'key-col' : c.field === 'is_panel' ? 'center' : c.field === 'description' ? 'desc-col' : '',
		render: (v: string | number | boolean | null, type: string, r: EelItem) => {
			if (c.field === 'is_panel') return type === 'display' ? (v ? '<span class="yes">✓</span>' : '') : v ? 'Yes' : 'No';
			let t = c.ref ? labelOf(c.ref, (v as string) || null) : v == null ? '' : String(v);
			if (type === 'sort' || type === 'type') return c.num && v != null ? Number(v) : t.toLowerCase();
			if (type !== 'display') return t;
			if (c.field === 'tag' && clashes[r.id]) return `${escapeHtml(t)} <span class="warnText" title="Also in ${escapeHtml(clashes[r.id].join(', '))}">⚠</span>`;
			if (c.ref && t) t = `<span title="${escapeHtml(labelOf(c.ref, v as string, true))}">${escapeHtml(t)}</span>`;
			else t = escapeHtml(t);
			return t;
		},
	}));
	const selects: Record<number, SelectFilter<EelItem>> = {};
	COLS.forEach((c, i) => {
		if (c.filter !== 'select') return;
		const opts = c.ref ? choices(c.ref).map((x) => ({ value: x.id, label: labelOf(c.ref!, x.id, true) }))
			: c.field === 'rating_unit' ? RATING_UNITS.map((u) => ({ value: u, label: u }))
			: c.field === 'phases' ? PHASES.map((u) => ({ value: u, label: u }))
			: [{ value: 'true', label: 'Panels' }, { value: 'false', label: 'Not panels' }];
		selects[i] = {
			options: [{ value: '', label: 'All' }, ...(c.field === 'is_panel' ? [] : [{ value: '__none', label: '(blank)' }]), ...opts],
			test: (v, r) => v === '' || (v === '__none' ? !r[c.field] : String(r[c.field]) === v),
		};
	});
	table = createFilteredTable<EelItem>(host.value, columns.length, {
		data: items.value,
		columns,
		order: [[0, 'asc']],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: 'Electrical Equipment List' },
		],
		language: { search: 'Search all:', emptyTable: 'No equipment yet. Use "Add equipment".' },
	}, selects);
}

// -- the form ---------------------------------------------------------------------------
const editing = ref<{ isNew: boolean; form: EelForm } | null>(null);
const formErrors = ref<Record<string, string>>({});

function open(item: EelItem | null) {
	formErrors.value = {};
	kl.error = null;
	const blank: EelForm = {
		id: newId(), tag: '', description: '', equipment_code_id: '', plant_area_id: '', vendor_package_id: null, load_type_id: null,
		rating: '', rating_unit: null, voltage: '', phases: null, is_panel: false, supplied_from: null, manufacturer: '',
		model_number: '', supplied_by_id: null, installed_by_id: null, terminated_by_id: null,
	};
	editing.value = {
		isNew: !item,
		form: item ? { ...item, rating: item.rating ?? '', voltage: item.voltage == null ? '' : String(item.voltage) } : blank,
	};
}

function onClick(e: MouseEvent) {
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as EelItem | undefined;
	if (row) open(row);
}

/** Choosing a load type copies its kW or Amps, voltage and phases (they can still be changed). */
function pickLoadType(id: string) {
	const f = editing.value!.form;
	f.load_type_id = id || null;
	const t = view.value?.choices.load_types.find((x) => x.id === id);
	if (t) Object.assign(f, { rating_unit: t.rating_unit, voltage: String(t.voltage), phases: t.phases });
}

// Supplied from: Primary Supply and the active panels, but not the item itself.
const supplyChoices = computed(() => choices('supplied_from').filter((c) => c.id !== `${EEL_SOURCE}/${editing.value?.form.id}`));

async function save(addAnother = false) {
	const e = editing.value;
	if (!e) return;
	formErrors.value = eelProblems(e.form, items.value.filter((r) => r.id !== e.form.id));
	if (Object.keys(formErrors.value).length) return;
	if (!(await kl.saveEelItem(e.form))) {
		// The engine names problems as "<item id>.<field>"; show this item's beside its inputs.
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
	if (!e || e.isNew || !confirm(`Delete ${e.form.tag}? Its Load List row stays, marked deleted.`)) return;
	if (await kl.deleteEelItem(e.form.id)) editing.value = null;
}

watch(() => [host.value, kl.eel], build);
// A field's message goes as soon as that field is changed (Save checks everything again).
let shown: Record<string, unknown> = {};
watch(() => (editing.value ? { ...editing.value.form } : null), (now) => {
	if (!now) return void (shown = {});
	for (const k of Object.keys(formErrors.value)) {
		const field = k.split('.').pop()!;
		if (field in shown && shown[field] !== (now as Record<string, unknown>)[field]) delete formErrors.value[k];
	}
	shown = now;
}, { deep: true });
onBeforeUnmount(() => table?.api.destroy());
const REFS: { field: Ref; title: string; required?: boolean }[] = [
	{ field: 'equipment_code_id', title: 'Equipment type', required: true },
	{ field: 'plant_area_id', title: 'Plant area', required: true },
	{ field: 'vendor_package_id', title: 'Vendor package' },
];
const BYS: { field: Ref; title: string }[] = [
	{ field: 'supplied_by_id', title: 'Supplied by' }, { field: 'installed_by_id', title: 'Installed by' },
	{ field: 'terminated_by_id', title: 'Terminated by' },
];
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-eel">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Electrical Equipment List</h2>
			<span class="hint small">{{ items.length }} item(s), each also a row of the Load List. Click a row to edit or delete it.</span>
			<span class="spacer" />
			<ListUndoButtons list="eel" />
			<HistoryButton entity="eel" record-id="eel" label="Electrical Equipment List" />
			<ListWorkbook list-id="eel" name="Electrical Equipment List" />
			<button type="button" @click="open(null)">Add equipment</button>
		</div>
		<p v-if="kl.error && !editing" class="error">{{ kl.error }}</p>
		<div v-if="view && Object.keys(view.clashes).length" class="chips">
			<span class="chip warn-chip">⚠ {{ Object.keys(view.clashes).length }} tag(s) are now also in an import (marked ⚠); tags must be unique.</span>
		</div>
		<div class="results mel-grid">
			<div ref="host" class="result-table ref-rows" @click="onClick" />
		</div>

		<AppModal class="eel-form" :open="!!editing" :title="editing?.isNew ? 'Add equipment' : `Edit ${editing?.form.tag}`" @close="close">
			<form v-if="editing" class="form-grid two-col" @submit.prevent="save()">
				<label class="field">
					<span>Tag number<span class="req"> *</span></span>
					<input v-model="editing.form.tag" type="text" class="mono" :class="{ invalid: formErrors.tag }" />
					<span v-if="formErrors.tag" class="warn small">{{ formErrors.tag }}</span>
				</label>
				<label class="field">
					<span>Description<span class="req"> *</span></span>
					<input v-model="editing.form.description" type="text" :class="{ invalid: formErrors.description }" />
					<span v-if="formErrors.description" class="warn small">{{ formErrors.description }}</span>
				</label>
				<label v-for="r in REFS" :key="r.field" class="field">
					<span>{{ r.title }}<span v-if="r.required" class="req"> *</span></span>
					<select v-model="editing.form[r.field]" :class="{ invalid: formErrors[r.field] }">
						<option :value="r.required ? '' : null">—</option>
						<option v-for="c in choices(r.field)" :key="c.id" :value="c.id">{{ NB.repeat(c.depth) }}{{ c.label }}</option>
					</select>
					<span v-if="formErrors[r.field]" class="warn small">{{ formErrors[r.field] }}</span>
				</label>
				<label class="field">
					<span>Load type</span>
					<select :value="editing.form.load_type_id ?? ''" :class="{ invalid: formErrors.load_type_id }"
						title="Choosing a load type copies its kW or Amps, voltage and phases" @change="pickLoadType(($event.target as HTMLSelectElement).value)">
						<option value="">—</option>
						<option v-for="c in choices('load_type_id')" :key="c.id" :value="c.id">{{ c.label }}</option>
					</select>
					<span v-if="formErrors.load_type_id" class="warn small">{{ formErrors.load_type_id }}</span>
				</label>
				<fieldset class="field wide electrical">
					<legend>Electrical</legend>
					<label class="field">
						<span>Rating</span>
						<input v-model="editing.form.rating" type="text" inputmode="decimal" placeholder="Number" :class="{ invalid: formErrors.rating }" />
						<span v-if="formErrors.rating" class="warn small">{{ formErrors.rating }}</span>
					</label>
					<label class="field">
						<span>kW or Amps</span>
						<select v-model="editing.form.rating_unit"><option :value="null">—</option><option v-for="u in RATING_UNITS" :key="u" :value="u">{{ u }}</option></select>
					</label>
					<label class="field">
						<span>Voltage</span>
						<input v-model="editing.form.voltage" type="text" inputmode="numeric" placeholder="e.g. 415" :class="{ invalid: formErrors.voltage }" />
						<span v-if="formErrors.voltage" class="warn small">{{ formErrors.voltage }}</span>
					</label>
					<label class="field">
						<span>Phases</span>
						<select v-model="editing.form.phases"><option :value="null">—</option><option v-for="u in PHASES" :key="u" :value="u">{{ u }}</option></select>
					</label>
					<label class="field check">
						<input v-model="editing.form.is_panel" type="checkbox" :class="{ invalid: formErrors.is_panel }" /><span>Distribution panel</span>
					</label>
					<label class="field">
						<span>Supplied from</span>
						<select v-model="editing.form.supplied_from" :class="{ invalid: formErrors.supplied_from }">
							<option :value="null">— not set —</option>
							<option v-for="c in supplyChoices" :key="c.id" :value="c.id">{{ c.label }}</option>
						</select>
					</label>
					<span v-if="formErrors.is_panel || formErrors.supplied_from" class="warn small wide">{{ formErrors.is_panel || formErrors.supplied_from }}</span>
				</fieldset>
				<label class="field">
					<span>Manufacturer</span>
					<input v-model="editing.form.manufacturer" type="text" />
				</label>
				<label class="field">
					<span>Model number</span>
					<input v-model="editing.form.model_number" type="text" />
				</label>
				<label v-for="r in BYS" :key="r.field" class="field">
					<span>{{ r.title }}</span>
					<select v-model="editing.form[r.field]" :class="{ invalid: formErrors[r.field] }">
						<option :value="null">—</option>
						<option v-for="c in choices(r.field)" :key="c.id" :value="c.id">{{ c.label }}</option>
					</select>
					<span v-if="formErrors[r.field]" class="warn small">{{ formErrors[r.field] }}</span>
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
