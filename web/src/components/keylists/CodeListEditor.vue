<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import ListWorkbook from './ListWorkbook.vue';
import type { ColumnsConfig } from 'datatables.net';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { type CodeListId, type CodeRow, type Discipline, codeRowProblems } from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import HistoryButton from '../audit/HistoryButton.vue';
import AppModal from '../common/AppModal.vue';

// Equipment Codes and Instrument Codes: a grid of every row; a row is added or edited in a
// form and saved from there. Equipment codes have disciplines, instrument codes a PLC code.
const props = defineProps<{ listId: CodeListId }>();
const CONFIG = {
	'equipment-codes': { title: 'Equipment Codes', noun: 'equipment code', entity: 'equipment_codes' },
	'instrument-codes': { title: 'Instrument Codes', noun: 'instrument code', entity: 'instrument_codes' },
} as const;
const cfg = computed(() => CONFIG[props.listId]);
const hasDisciplines = computed(() => props.listId === 'equipment-codes');

const kl = useKeyLists();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<CodeRow> | null = null;
const items = computed(() => kl.codeLists[props.listId]?.items ?? []);
// the project's Disciplines enum (Project lists, Enums)
const DISCIPLINES = computed(() => kl.overview?.disciplines ?? []);
const disciplineName = (code: string) => DISCIPLINES.value.find((d) => d.code === code)?.name ?? code;
const text = (t: string, type: string) => (type === 'display' ? escapeHtml(t) : t);

function build() {
	if (!host.value || !kl.codeLists[props.listId]) return;
	table?.api.destroy();
	const columns: ColumnsConfig[] = [
		{ title: 'Code <span class="req" title="Required">*</span>', data: 'code', className: 'key-col', render: text },
		{ title: 'Name <span class="req" title="Required">*</span>', data: 'name', render: text },
		{ title: 'Description', data: 'description', className: 'desc-col', render: (t: string, type: string) => (type === 'display' ? `<span title="${escapeHtml(t)}">${escapeHtml(t)}</span>` : t) },
		hasDisciplines.value
			? {
				title: 'Disciplines', data: (r: CodeRow) => (r.disciplines ?? []).join(', '),
				render: (t: string, type: string, r: CodeRow) => (type === 'display'
					? (r.disciplines ?? []).map((d) => `<span class="disc" title="${escapeHtml(disciplineName(d))}">${d}</span>`).join('')
					: t),
			}
			: { title: 'PLC code', data: 'plc_code', className: 'plc-col', render: text },
	];
	const selects: Record<number, SelectFilter<CodeRow>> = {};
	if (hasDisciplines.value) {
		selects[3] = {
			options: [{ value: '', label: 'All' }, { value: '__none', label: '(none)' },
				...DISCIPLINES.value.map((d) => ({ value: d.code, label: `${d.code} – ${d.name}` }))],
			test: (v, r) => v === '' || (v === '__none' ? !r.disciplines?.length : !!r.disciplines?.includes(v as Discipline)),
		};
	}
	table = createFilteredTable<CodeRow>(host.value, columns.length, {
		data: items.value,
		columns,
		order: [[0, 'asc']],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: cfg.value.title },
		],
		language: { search: 'Search all:', emptyTable: `No ${cfg.value.noun}s yet. Use "Add ${cfg.value.noun}".` },
	}, selects);
}

// -- the form ---------------------------------------------------------------------------
const editing = ref<{ isNew: boolean; row: CodeRow } | null>(null);
const formErrors = ref<Record<string, string>>({});

function open(row: CodeRow | null) {
	formErrors.value = {};
	kl.error = null;
	const extra = hasDisciplines.value ? { disciplines: [...(row?.disciplines ?? [])] } : { plc_code: row?.plc_code ?? '' };
	editing.value = {
		isNew: !row,
		row: { id: row?.id ?? newId(), code: row?.code ?? '', name: row?.name ?? '', description: row?.description ?? '', ...extra },
	};
}

function onClick(e: MouseEvent) {
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as CodeRow | undefined;
	if (row) open(row);
}

function toggle(d: Discipline, on: boolean) {
	const r = editing.value!.row;
	const now = new Set(r.disciplines ?? []);
	if (on) now.add(d);
	else now.delete(d);
	r.disciplines = DISCIPLINES.value.map((x) => x.code).filter((c) => now.has(c));
}

async function save(addAnother = false) {
	const e = editing.value;
	if (!e) return;
	formErrors.value = codeRowProblems(e.row, items.value.filter((r) => r.id !== e.row.id));
	if (Object.keys(formErrors.value).length) return;
	if (!(await kl.saveCodeRow(props.listId, e.row))) {
		// The engine names problems as "<row id>.<field>"; show this row's beside its inputs.
		const mine: Record<string, string> = {};
		for (const [k, msg] of Object.entries(kl.fieldErrors)) if (k.startsWith(`${e.row.id}.`)) mine[k.slice(e.row.id.length + 1)] = msg;
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
	if (!e || e.isNew || !confirm(`Delete the ${cfg.value.noun} "${e.row.code}"?`)) return;
	if (await kl.deleteCodeRow(props.listId, e.row.id)) editing.value = null;
}

watch(() => [host.value, kl.codeLists[props.listId]], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-codes">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">{{ cfg.title }}</h2>
			<span class="hint small">{{ items.length }} {{ cfg.noun }}(s). Click a row to edit or delete it.</span>
			<span class="spacer" />
			<HistoryButton :entity="cfg.entity" :record-id="listId" :label="cfg.title" />
			<ListWorkbook :list-id="listId" :name="cfg.title" />
			<button type="button" @click="open(null)">Add {{ cfg.noun }}</button>
		</div>
		<p v-if="kl.error && !editing" class="error">{{ kl.error }}</p>
		<div class="results mel-grid">
			<div ref="host" class="result-table ref-rows" @click="onClick" />
		</div>

		<AppModal :open="!!editing" :title="`${editing?.isNew ? 'Add' : 'Edit'} ${cfg.noun}`" @close="close">
			<form v-if="editing" class="form-grid two-col" @submit.prevent="save()">
				<label class="field">
					<span>Code<span class="req"> *</span></span>
					<input v-model="editing.row.code" type="text" class="mono" :class="{ invalid: formErrors.code }" />
					<span v-if="formErrors.code" class="warn small">{{ formErrors.code }}</span>
				</label>
				<label class="field">
					<span>Name<span class="req"> *</span></span>
					<input v-model="editing.row.name" type="text" :class="{ invalid: formErrors.name }" />
					<span v-if="formErrors.name" class="warn small">{{ formErrors.name }}</span>
				</label>
				<label class="field wide">
					<span>Description</span>
					<input v-model="editing.row.description" type="text" />
				</label>
				<fieldset v-if="hasDisciplines" class="field wide disciplines" :class="{ invalid: formErrors.disciplines }">
					<legend>Disciplines</legend>
					<label v-for="d in DISCIPLINES" :key="d.code" class="disc-pick">
						<input type="checkbox" :checked="editing.row.disciplines?.includes(d.code)"
							@change="toggle(d.code, ($event.target as HTMLInputElement).checked)" />
						<span class="disc">{{ d.code }}</span> {{ d.name }}
					</label>
					<span v-if="formErrors.disciplines" class="warn small">{{ formErrors.disciplines }}</span>
				</fieldset>
				<label v-else class="field">
					<span>PLC code</span>
					<input v-model="editing.row.plc_code" type="text" class="mono" placeholder="e.g. AI" />
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
