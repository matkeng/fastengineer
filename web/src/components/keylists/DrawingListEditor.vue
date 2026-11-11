<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The Drawing List: the project's register of drawings. A grid of every drawing; one is added
// or edited in a form and saved from there. Discipline, type and status are fixed choices from
// the project's Enums; an equipment tag that is in neither the MEL nor the Electrical Equipment
// List is warned about, not refused.
import type { ColumnsConfig } from 'datatables.net';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { type DrawingChoice, type DrawingRow, type EnumItem, enumLabel } from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import { useProjects } from '../../stores/projects';
import HistoryButton from '../audit/HistoryButton.vue';
import AppModal from '../common/AppModal.vue';
import ListWorkbook from './ListWorkbook.vue';

const kl = useKeyLists();
const projects = useProjects();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<DrawingRow> | null = null;
const view = computed(() => kl.drawings);
const items = computed(() => view.value?.items ?? []);
const CHOICES: DrawingChoice[] = ['discipline', 'drawing_type', 'status'];
const choices = (f: DrawingChoice): EnumItem[] => view.value?.choices[f] ?? [];
const warned = computed(() => items.value.filter((d) => d.unknown_equipment.length).length);

type Field = Exclude<keyof DrawingRow, 'id' | 'unknown_equipment' | `${DrawingChoice}_id`>;
const COLS = computed(() => (view.value?.columns ?? []) as { field: Field; heading: string }[]);
/** dd/mm/yyyy -> yyyy-mm-dd (for sorting, and for the form's date input). */
const iso = (d: string) => (/^\d{2}\/\d{2}\/\d{4}$/.test(d) ? `${d.slice(6)}-${d.slice(3, 5)}-${d.slice(0, 2)}` : '');
const shown = (d: string) => (/^\d{4}-\d{2}-\d{2}$/.test(d) ? `${d.slice(8)}/${d.slice(5, 7)}/${d.slice(0, 4)}` : d);

function build() {
	if (!host.value || !view.value) return;
	table?.api.destroy();
	const columns = COLS.value.map((c): ColumnsConfig => ({
		title: escapeHtml(c.heading) + (c.field === 'number' ? ' <span class="req" title="Required">*</span>' : ''),
		data: (row: DrawingRow) => row[c.field] ?? '',
		className: c.field === 'number' ? 'key-col' : '',
		render: (v: string, type: string, row: DrawingRow) => {
			if (c.field === 'issue_date' && (type === 'sort' || type === 'type')) return iso(v);
			if (type !== 'display') return v;
			if (c.field === 'equipment_reference' && row.unknown_equipment.length) {
				return `${escapeHtml(v)} <span class="warnText" title="Not in the MEL or the Electrical Equipment List: ${escapeHtml(row.unknown_equipment.join(', '))}">⚠</span>`;
			}
			return escapeHtml(v);
		},
	}));
	const selects: Record<number, SelectFilter<DrawingRow>> = {};
	COLS.value.forEach((c, i) => {
		if (!(CHOICES as string[]).includes(c.field)) return;
		const f = c.field as DrawingChoice;
		selects[i] = {
			options: [{ value: '', label: 'All' }, { value: '__none', label: '(none)' }, ...choices(f).map((o) => ({ value: o.id, label: enumLabel(o) }))],
			test: (v, r) => v === '' || (v === '__none' ? !r[`${f}_id`] : r[`${f}_id`] === v),
		};
	});
	table = createFilteredTable<DrawingRow>(host.value, columns.length, {
		data: items.value,
		columns,
		order: [[0, 'asc']],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible' }, filename: 'Drawing List' },
		],
		language: { search: 'Search all:', emptyTable: 'No drawings yet. Use "Add drawing", or import a workbook.' },
	}, selects);
}

// -- the form ---------------------------------------------------------------------------
type Form = Record<Field, string> & { id: string };
const editing = ref<{ isNew: boolean; form: Form; ids: Record<DrawingChoice, string> } | null>(null);
const formErrors = ref<Record<string, string>>({});
const key = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
const TEXT: { field: Field; label: string; wide?: boolean; hint?: string }[] = [
	{ field: 'title_1', label: 'Title 1', wide: true }, { field: 'title_2', label: 'Title 2', wide: true }, { field: 'title_3', label: 'Title 3', wide: true },
];
const unknownNow = computed(() => {
	const e = editing.value;
	const saved = items.value.find((d) => d.id === e?.form.id);
	// the engine says which tags are unknown; it is shown for the reference as saved
	return e && saved && key(saved.equipment_reference) === key(e.form.equipment_reference) ? saved.unknown_equipment : [];
});

function open(row: DrawingRow | null) {
	formErrors.value = {};
	kl.error = null;
	const blank = Object.fromEntries(COLS.value.map((c) => [c.field, ''])) as Record<Field, string>;
	editing.value = {
		isNew: !row,
		form: row ? { ...blank, ...Object.fromEntries(COLS.value.map((c) => [c.field, row[c.field] ?? ''])), id: row.id, issue_date: iso(row.issue_date) } as Form
			: { ...blank, id: newId(), project_name: projects.current?.name ?? '' },
		ids: { discipline: row?.discipline_id ?? '', drawing_type: row?.drawing_type_id ?? '', status: row?.status_id ?? '' },
	};
}

function onClick(e: MouseEvent) {
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as DrawingRow | undefined;
	if (row) open(row);
}

async function save(addAnother = false) {
	const e = editing.value;
	if (!e) return;
	const errors: Record<string, string> = {};
	if (!key(e.form.number)) errors.number = 'Drawing number is required';
	else if (items.value.some((r) => r.id !== e.form.id && key(r.number) === key(e.form.number))) errors.number = 'Another drawing has this number';
	formErrors.value = errors;
	if (Object.keys(errors).length) return;
	// the choices go by id (so a renamed item is still the same one); the date as dd/mm/yyyy
	const row = { ...e.form, issue_date: shown(e.form.issue_date), discipline: '', drawing_type: '', status: '',
		discipline_id: e.ids.discipline || null, drawing_type_id: e.ids.drawing_type || null, status_id: e.ids.status || null };
	if (!(await kl.saveDrawing(row))) {
		const mine: Record<string, string> = {};
		for (const [k, msg] of Object.entries(kl.fieldErrors)) if (k.startsWith(`${e.form.id}.`)) mine[k.slice(e.form.id.length + 1)] = msg;
		formErrors.value = mine;
		return;
	}
	const saved = items.value.find((d) => d.id === e.form.id);
	kl.message = saved?.unknown_equipment.length
		? `Saved. Not in the MEL or the Electrical Equipment List: ${saved.unknown_equipment.join(', ')}` : 'Saved';
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
	if (!e || e.isNew || !confirm(`Delete the drawing "${e.form.number}" from the list?`)) return;
	if (await kl.deleteDrawing(e.form.id)) editing.value = null;
}

watch(() => [host.value, kl.drawings], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-cables key-drawings">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Drawing List</h2>
			<span class="hint small">
				{{ items.length }} drawing(s). Click a row to edit or delete it.
				<span v-if="warned" class="warnText" title="Equipment references with a tag that is in neither the MEL nor the Electrical Equipment List"> {{ warned }} with unknown equipment.</span>
			</span>
			<span class="spacer" />
			<span v-if="kl.message && !editing" class="saved" :title="kl.message">✓ {{ kl.message }}</span>
			<HistoryButton entity="drawing_list" record-id="drawing-list" label="Drawing List" />
			<ListWorkbook list-id="drawing-list" name="Drawing List" />
			<button type="button" :disabled="kl.busy" @click="open(null)">Add drawing</button>
		</div>
		<p v-if="kl.error && !editing" class="error">{{ kl.error }}</p>
		<div class="results mel-grid"><div ref="host" class="result-table" @click="onClick" /></div>

		<AppModal class="drawing-form" :open="!!editing" :title="editing?.isNew ? 'Add drawing' : 'Edit drawing'" @close="close">
			<form v-if="editing" class="form-grid two-col" @submit.prevent="save()">
				<label class="field">
					<span>Drawing number<span class="req"> *</span></span>
					<input v-model="editing.form.number" type="text" class="mono" :class="{ invalid: formErrors.number }" />
					<span v-if="formErrors.number" class="warn small">{{ formErrors.number }}</span>
				</label>
				<label class="field">
					<span>Project name</span>
					<input v-model="editing.form.project_name" type="text" />
				</label>
				<label v-for="t in TEXT" :key="t.field" class="field wide">
					<span>{{ t.label }}</span>
					<input v-model="editing.form[t.field]" type="text" />
				</label>
				<label v-for="f in CHOICES" :key="f" class="field">
					<span>{{ COLS.find((c) => c.field === f)?.heading }}</span>
					<select v-model="editing.ids[f]" :class="{ invalid: formErrors[f] }">
						<option value="">—</option>
						<option v-for="o in choices(f)" :key="o.id" :value="o.id">{{ o.code && o.code !== o.name ? `${o.code} – ${o.name}` : o.name }}</option>
					</select>
					<span v-if="formErrors[f]" class="warn small">{{ formErrors[f] }}</span>
				</label>
				<label class="field">
					<span>Revision</span>
					<input v-model="editing.form.revision" type="text" class="mono" />
				</label>
				<label class="field">
					<span>Issue date</span>
					<input v-model="editing.form.issue_date" type="date" :class="{ invalid: formErrors.issue_date }" />
					<span v-if="formErrors.issue_date" class="warn small">{{ formErrors.issue_date }}</span>
				</label>
				<label class="field">
					<span>Vendor drg number</span>
					<input v-model="editing.form.vendor_drg_number" type="text" class="mono" />
				</label>
				<label class="field">
					<span>Vendor reference</span>
					<input v-model="editing.form.vendor_reference" type="text" />
				</label>
				<label class="field wide">
					<span>Equipment reference</span>
					<input v-model="editing.form.equipment_reference" type="text" class="mono" placeholder="One or more tags, separated by commas" />
					<span v-if="unknownNow.length" class="warn small">Not in the MEL or the Electrical Equipment List: {{ unknownNow.join(', ') }}. It is saved as typed.</span>
					<span v-else class="hint small">A tag that is in neither the MEL nor the Electrical Equipment List is flagged after saving; it doesn't stop the save.</span>
				</label>
				<label class="field wide">
					<span>Scope</span>
					<input v-model="editing.form.scope" type="text" />
				</label>
				<button type="submit" hidden />
			</form>
			<p class="hint small">Discipline, type and status are picked from this project's <strong>Enums</strong> (Project lists, Enums), where the choices can be changed.</p>
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
