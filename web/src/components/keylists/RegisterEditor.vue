<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// A register of the project: the Drawing List or the Document List (the same thing, the
// documents with one title line). A grid of every item; one is added or edited in a form and
// saved from there. Discipline, type and status are fixed choices from the project's Enums; an
// equipment tag that is in neither the MEL nor the Electrical Equipment List is warned about,
// not refused. The columns, headings and choices all come from the engine.
import type { ColumnsConfig } from 'datatables.net';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { type EnumItem, type RegisterKind, type RegisterRow, enumLabel, linkHref } from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import { useProjects } from '../../stores/projects';
import HistoryButton from '../audit/HistoryButton.vue';
import AppModal from '../common/AppModal.vue';
import ListWorkbook from './ListWorkbook.vue';

const props = defineProps<{ kind: RegisterKind }>();
const kl = useKeyLists();
const projects = useProjects();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<RegisterRow> | null = null;
const view = computed(() => kl.registers[props.kind]);
const items = computed(() => view.value?.items ?? []);
const name = computed(() => view.value?.name ?? '');
const item = computed(() => view.value?.item ?? 'item');
const entity = computed(() => props.kind.replace('-', '_'));
const COLS = computed(() => view.value?.columns ?? []);
const CHOICES = computed(() => Object.keys(view.value?.choices ?? {}));
const choices = (f: string): EnumItem[] => view.value?.choices[f] ?? [];
const isChoice = (f: string) => CHOICES.value.includes(f);
const WIDE = (f: string) => f.startsWith('title') || f === 'scope';
const text = (row: RegisterRow, f: string) => String(row[f] ?? '');
const warned = computed(() => items.value.filter((d) => d.unknown_equipment.length).length);
/** dd/mm/yyyy -> yyyy-mm-dd (for sorting, and for the form's date input). */
const iso = (d: string) => (/^\d{2}\/\d{2}\/\d{4}$/.test(d) ? `${d.slice(6)}-${d.slice(3, 5)}-${d.slice(0, 2)}` : '');
const shown = (d: string) => (/^\d{4}-\d{2}-\d{2}$/.test(d) ? `${d.slice(8)}/${d.slice(5, 7)}/${d.slice(0, 4)}` : d);

function build() {
	if (!host.value || !view.value) return;
	table?.api.destroy();
	const columns = COLS.value.map((c): ColumnsConfig => ({
		title: escapeHtml(c.heading) + (c.field === 'number' ? ' <span class="req" title="Required">*</span>' : ''),
		data: (row: RegisterRow) => text(row, c.field),
		className: c.field === 'number' ? 'key-col' : '',
		render: (v: string, type: string, row: RegisterRow) => {
			if (c.field === 'issue_date' && (type === 'sort' || type === 'type')) return iso(v);
			if (type !== 'display') return v;
			if (c.field === 'equipment_reference' && row.unknown_equipment.length) {
				return `${escapeHtml(v)} <span class="warnText" title="Not in the MEL or the Electrical Equipment List: ${escapeHtml(row.unknown_equipment.join(', '))}">⚠</span>`;
			}
			if (c.field === 'hyperlink' && v) {
				const href = linkHref(v);
				const label = escapeHtml(v.length > 48 ? `${v.slice(0, 47)}…` : v);
				return href ? `<a class="drawing-link" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer" title="Open ${escapeHtml(v)}">🔗 ${label}</a>` : label;
			}
			return escapeHtml(v);
		},
	}));
	const selects: Record<number, SelectFilter<RegisterRow>> = {};
	COLS.value.forEach((c, i) => {
		if (!isChoice(c.field)) return;
		selects[i] = {
			options: [{ value: '', label: 'All' }, { value: '__none', label: '(none)' }, ...choices(c.field).map((o) => ({ value: o.id, label: enumLabel(o) }))],
			test: (v, r) => v === '' || (v === '__none' ? !r[`${c.field}_id`] : r[`${c.field}_id`] === v),
		};
	});
	table = createFilteredTable<RegisterRow>(host.value, columns.length, {
		data: items.value,
		columns,
		order: [[0, 'asc']],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible' }, filename: name.value },
		],
		language: { search: 'Search all:', emptyTable: `No ${item.value}s yet. Use "Add ${item.value}", or import a workbook.` },
	}, selects);
}

// -- the form ---------------------------------------------------------------------------
const editing = ref<{ isNew: boolean; id: string; form: Record<string, string>; ids: Record<string, string> } | null>(null);
const formErrors = ref<Record<string, string>>({});
const key = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
const unknownNow = computed(() => {
	const e = editing.value;
	const saved = items.value.find((d) => d.id === e?.id);
	// the engine says which tags are unknown; it is shown for the reference as saved
	return e && saved && key(saved.equipment_reference) === key(e.form.equipment_reference ?? '') ? saved.unknown_equipment : [];
});

function open(row: RegisterRow | null) {
	formErrors.value = {};
	kl.error = null;
	const form = Object.fromEntries(COLS.value.map((c) => [c.field, row ? text(row, c.field) : '']));
	if (row) form.issue_date = iso(row.issue_date);
	else form.project_name = projects.current?.name ?? '';
	editing.value = {
		isNew: !row, id: row?.id ?? newId(), form,
		ids: Object.fromEntries(CHOICES.value.map((f) => [f, row ? String(row[`${f}_id`] ?? '') : ''])),
	};
}

const copied = ref(false);
async function copyLink(link: string) {
	try {
		await navigator.clipboard.writeText(link);
		copied.value = true;
		setTimeout(() => { copied.value = false; }, 2000);
	} catch { /* the clipboard is not available: the link can still be selected in the field */ }
}

function onClick(e: MouseEvent) {
	if ((e.target as HTMLElement).closest('a.drawing-link')) return; // the link opens; the form doesn't
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as RegisterRow | undefined;
	if (row) open(row);
}

async function save(addAnother = false) {
	const e = editing.value;
	if (!e) return;
	const errors: Record<string, string> = {};
	const link = (e.form.hyperlink ?? '').trim();
	if (link && /^[a-z][a-z0-9+.-]+:/i.test(link) && !/^(https?:\/\/\S|file:)/i.test(link)) errors.hyperlink = 'A link is a web address (https://...) or the path of a file or folder';
	const numberName = COLS.value[0]?.heading ?? 'Number';
	if (!key(e.form.number)) errors.number = `${numberName} is required`;
	else if (items.value.some((r) => r.id !== e.id && key(r.number) === key(e.form.number))) errors.number = `Another ${item.value} has this number`;
	formErrors.value = errors;
	if (Object.keys(errors).length) return;
	// the choices go by id (so a renamed item is still the same one); the date as dd/mm/yyyy
	const row: Record<string, string | null> = { ...e.form, id: e.id, issue_date: shown(e.form.issue_date ?? '') };
	for (const f of CHOICES.value) {
		row[f] = '';
		row[`${f}_id`] = e.ids[f] || null;
	}
	if (!(await kl.saveRegisterItem(props.kind, row as { id: string }))) {
		const mine: Record<string, string> = {};
		for (const [k, msg] of Object.entries(kl.fieldErrors)) if (k.startsWith(`${e.id}.`)) mine[k.slice(e.id.length + 1)] = msg;
		formErrors.value = mine;
		return;
	}
	const saved = items.value.find((d) => d.id === e.id);
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
	if (!e || e.isNew || !confirm(`Delete the ${item.value} "${e.form.number}" from the list?`)) return;
	if (await kl.deleteRegisterItem(props.kind, e.id)) editing.value = null;
}

watch(() => [host.value, view.value], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-cables key-drawings">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">{{ name }}</h2>
			<span class="hint small">
				{{ items.length }} {{ item }}(s). Click a row to edit or delete it.
				<span v-if="warned" class="warnText" title="Equipment references with a tag that is in neither the MEL nor the Electrical Equipment List"> {{ warned }} with unknown equipment.</span>
			</span>
			<span class="spacer" />
			<span v-if="kl.message && !editing" class="saved" :title="kl.message">✓ {{ kl.message }}</span>
			<HistoryButton :entity="entity" :record-id="kind" :label="name" />
			<ListWorkbook :list-id="kind" :name="name" />
			<button type="button" :disabled="kl.busy" @click="open(null)">Add {{ item }}</button>
		</div>
		<p v-if="kl.error && !editing" class="error">{{ kl.error }}</p>
		<div class="results mel-grid"><div ref="host" class="result-table" @click="onClick" /></div>

		<AppModal class="drawing-form" :open="!!editing" :title="`${editing?.isNew ? 'Add' : 'Edit'} ${item}`" @close="close">
			<form v-if="editing" class="form-grid two-col" @submit.prevent="save()">
				<template v-for="c in COLS" :key="c.field">
					<label v-if="isChoice(c.field)" class="field">
						<span>{{ c.heading }}</span>
						<select v-model="editing.ids[c.field]" :class="{ invalid: formErrors[c.field] }">
							<option value="">—</option>
							<option v-for="o in choices(c.field)" :key="o.id" :value="o.id">{{ o.code && o.code !== o.name ? `${o.code} – ${o.name}` : o.name }}</option>
						</select>
						<span v-if="formErrors[c.field]" class="warn small">{{ formErrors[c.field] }}</span>
					</label>
					<label v-else-if="c.field === 'issue_date'" class="field">
						<span>{{ c.heading }}</span>
						<input v-model="editing.form.issue_date" type="date" :class="{ invalid: formErrors.issue_date }" />
						<span v-if="formErrors.issue_date" class="warn small">{{ formErrors.issue_date }}</span>
					</label>
					<label v-else-if="c.field === 'equipment_reference'" class="field wide">
						<span>{{ c.heading }}</span>
						<input v-model="editing.form.equipment_reference" type="text" class="mono" placeholder="One or more tags, separated by commas" />
						<span v-if="unknownNow.length" class="warn small">Not in the MEL or the Electrical Equipment List: {{ unknownNow.join(', ') }}. It is saved as typed.</span>
						<span v-else class="hint small">A tag that is in neither the MEL nor the Electrical Equipment List is flagged after saving; it doesn't stop the save.</span>
					</label>
					<label v-else-if="c.field === 'hyperlink'" class="field wide">
						<span>{{ c.heading }}</span>
						<span class="row tight">
							<input v-model="editing.form.hyperlink" type="text" class="mono" :class="{ invalid: formErrors.hyperlink }"
								placeholder="https://…  or the path of the file, e.g. \\server\documents\3510\…pdf" />
							<a v-if="linkHref(editing.form.hyperlink)" class="button-link" :href="linkHref(editing.form.hyperlink)" target="_blank" rel="noopener noreferrer">Open</a>
							<button type="button" class="secondary small" :disabled="!editing.form.hyperlink.trim()" @click="copyLink(editing.form.hyperlink.trim())">{{ copied ? 'Copied' : 'Copy' }}</button>
						</span>
						<span v-if="formErrors.hyperlink" class="warn small">{{ formErrors.hyperlink }}</span>
						<span v-else class="hint small">Where the {{ item }} is kept: a web address, or a file or folder path. A web address opens in the browser; a file path may be blocked from opening here, so Copy puts it on the clipboard to paste into File Explorer.</span>
					</label>
					<label v-else class="field" :class="{ wide: WIDE(c.field) }">
						<span>{{ c.heading }}<span v-if="c.field === 'number'" class="req"> *</span></span>
						<input v-model="editing.form[c.field]" type="text" :class="{ invalid: formErrors[c.field], mono: /number|revision/.test(c.field) }" />
						<span v-if="formErrors[c.field]" class="warn small">{{ formErrors[c.field] }}</span>
					</label>
				</template>
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
