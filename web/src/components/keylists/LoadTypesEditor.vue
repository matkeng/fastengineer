<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import ListWorkbook from './ListWorkbook.vue';
import type { ColumnsConfig } from 'datatables.net';
import { invoke } from '@tauri-apps/api/core';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { runningInTauri } from '../../lib/engine';
import {
	PHASES, RATING_UNITS, type AttachedFile, type LoadType, type LoadTypeField, type LoadTypeForm, fileSize, loadTypeProblems,
} from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import HistoryButton from '../audit/HistoryButton.vue';
import AppModal from '../common/AppModal.vue';
import EditGrid, { type CellEdit, type GridColumn } from '../common/EditGrid.vue';

// Load types: a grid of every row; a row is added or edited in a form and saved from there.
// Each load type also holds predefined rows for the deliverable lists (one tab per list): every
// load of that type in the Load List produces those rows, with the <<tags>> filled in from it.
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
	// The attached PDF: its name opens it (see onClick).
	columns.push({
		title: 'PDF',
		data: (row: LoadType) => row.pdf?.file_name ?? '',
		className: 'pdf-col',
		render: (name: string, type: string, row: LoadType) => {
			if (type !== 'display') return name.toLowerCase();
			return name ? `<button type="button" class="link pdf-link" data-pdf="${escapeHtml(row.id)}" title="Open ${escapeHtml(name)}">📄 ${escapeHtml(name)}</button>` : '';
		},
	});
	columns.push({
		title: 'Rows',
		data: (row: LoadType) => rowCount(row.rows),
		className: 'dt-right',
		render: (n: number, type: string, row: LoadType) => {
			if (type !== 'display') return n;
			const tip = lists.value.map((l) => `${l.name}: ${row.rows?.[l.key]?.length ?? 0}`).join('\n');
			return n ? `<span title="${escapeHtml(tip)}">${n}</span>` : '<span class="hint" title="No predefined rows: loads of this type add nothing to the deliverables">–</span>';
		},
	});
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
	selects[COLS.length] = {
		options: [{ value: '', label: 'All' }, { value: 'y', label: 'With PDF' }, { value: 'n', label: 'No PDF' }],
		test: (v, r) => v === '' || !!r.pdf === (v === 'y'),
	};
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
const editing = ref<{ isNew: boolean; form: LoadTypeForm; pdf: AttachedFile | null } | null>(null);
// The dialog's tab: 'details' or the key of a deliverable list.
const tab = ref('details');
const lists = computed(() => kl.templateLists?.lists ?? []);
const tagNames = computed(() => (kl.templateLists?.tags ?? []).map((t) => t.tag));
const rowCount = (rows: LoadType['rows'] | undefined) => Object.values(rows ?? {}).reduce((n, r) => n + r.length, 0);
const list = computed(() => lists.value.find((l) => l.key === tab.value) ?? null);
const listRows = computed(() => (list.value && editing.value ? (editing.value.form.rows[list.value.key] ??= []) : []));
// A list's row settings (the cable schedule's "Repeat") come first, then its columns.
const settings = computed(() => list.value?.settings ?? []);
const fields = computed(() => [...settings.value.map((s) => s.name), ...(list.value?.columns ?? [])]);
const gridCols = computed((): GridColumn[] => [
	...settings.value.map((s): GridColumn => ({ label: s.name, options: s.values, width: 130, badge: 'setting',
		title: `Blank: one row. ${s.values.join(' / ')}: one row for each of the load's power cables (parallel cables; single cores and their earth).` })),
	...(list.value?.columns ?? []).map((c): GridColumn => ({ label: c, width: /Description|Remarks|Code/.test(c) ? 200 : 130 })),
]);
const gridCells = computed(() => listRows.value.map((r) => fields.value.map((c) => r[c] ?? '')));
const tagClass = (r: number, c: number) => (/<<[^<>]+>>/.test(gridCells.value[r]?.[c] ?? '') ? 'has-tag' : '');

function setCells(edits: CellEdit[]) {
	const cols = fields.value;
	for (const e of edits) {
		const row = listRows.value[e.r];
		if (!row || !cols[e.c]) continue;
		if (e.value.trim()) row[cols[e.c]] = e.value;
		else delete row[cols[e.c]];
	}
}
const insertRows = (at: number, count: number) => listRows.value.splice(at, 0, ...Array.from({ length: count }, () => ({})));
function removeRows(idx: number[]) {
	if (!list.value || !editing.value) return;
	const drop = new Set(idx);
	editing.value.form.rows[list.value.key] = listRows.value.filter((_, i) => !drop.has(i));
}
// A PDF chosen in the form, or 'remove': applied when the form is saved.
const pdfChange = ref<File | 'remove' | null>(null);
const pdfInput = ref<HTMLInputElement | null>(null);
const newPdf = computed(() => (pdfChange.value instanceof File ? pdfChange.value : null));
const MAX_PDF = 50 * 1024 * 1024;
const formErrors = ref<Partial<Record<LoadTypeField | 'pdf', string>>>({});
const text = (v: string | number | null | undefined) => (v === null || v === undefined ? '' : String(v));

function open(row: LoadType | null) {
	formErrors.value = {};
	kl.error = null;
	pdfChange.value = null;
	tab.value = 'details';
	editing.value = {
		isNew: !row,
		pdf: row?.pdf ?? null,
		form: {
			id: row?.id ?? newId(), code: row?.code ?? '', name: row?.name ?? '', rating_unit: row?.rating_unit ?? '',
			voltage: text(row?.voltage), phases: row?.phases ?? '', from_value: text(row?.from_value), to_value: text(row?.to_value),
			std_drg: row?.std_drg ?? '', bucket_type: row?.bucket_type ?? '', load_type: row?.load_type ?? '',
			field_options: row?.field_options ?? '', multi_load: row?.multi_load ?? false, load_qty: text(row?.load_qty),
			rows: JSON.parse(JSON.stringify(row?.rows ?? {})),
		},
	};
}

function onClick(e: MouseEvent) {
	const link = (e.target as HTMLElement).closest<HTMLElement>('[data-pdf]');
	if (link) {
		const row = items.value.find((r) => r.id === link.dataset.pdf);
		if (row?.pdf) void view(row.id, row.pdf.file_name);
		return;
	}
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as LoadType | undefined;
	if (row) open(row);
}

async function save(addAnother = false) {
	const e = editing.value;
	if (!e) return;
	formErrors.value = loadTypeProblems(e.form, items.value.filter((r) => r.id !== e.form.id));
	if (Object.keys(formErrors.value).length) {
		tab.value = 'details';
		return;
	}
	if (pdfChange.value instanceof File) {
		const f = pdfChange.value;
		if (!/\.pdf$/i.test(f.name) && f.type !== 'application/pdf') formErrors.value.pdf = 'Choose a PDF file';
		else if (f.size > MAX_PDF) formErrors.value.pdf = 'The file is larger than 50 MB';
		if (formErrors.value.pdf) return;
	}
	if (!(await kl.saveLoadType(e.form))) {
		// The engine names problems as "<row id>.<field>"; show this row's beside its inputs.
		const mine: Partial<Record<LoadTypeField, string>> = {};
		for (const [k, msg] of Object.entries(kl.fieldErrors)) {
			if (k.startsWith(`${e.form.id}.`)) mine[k.slice(e.form.id.length + 1) as LoadTypeField] = msg;
		}
		formErrors.value = mine;
		if (Object.keys(mine).some((k) => !k.startsWith('rows'))) tab.value = 'details';
		return;
	}
	// The row is saved now; then the PDF (it can only be attached to a saved row).
	e.isNew = false;
	const change = pdfChange.value;
	if (change instanceof File ? !(await kl.attachLoadTypePdf(e.form.id, change)) : change === 'remove' && !(await kl.removeLoadTypePdf(e.form.id))) {
		formErrors.value = { pdf: `The load type was saved, but not the PDF change: ${kl.error}` };
		kl.error = null;
		return;
	}
	pdfChange.value = null;
	if (addAnother) {
		open(null);
		await nextTick();
		(document.querySelector('dialog.modal[open] input') as HTMLElement | null)?.focus();
	} else editing.value = null;
}

function choosePdf(ev: Event) {
	const input = ev.target as HTMLInputElement;
	const f = input.files?.[0];
	input.value = ''; // choosing the same file again still counts
	if (!f) return;
	pdfChange.value = f;
	delete formErrors.value.pdf;
}

function close() {
	pdfChange.value = null;
	editing.value = null;
	formErrors.value = {};
	kl.error = null;
}

async function remove() {
	const e = editing.value;
	if (!e || e.isNew || !confirm(`Delete the load type "${e.form.code}"?`)) return;
	if (await kl.deleteLoadType(e.form.id)) editing.value = null;
}

// -- viewing and saving a copy of a PDF --------------------------------------------------
const viewer = ref<{ id: string; name: string; url: string } | null>(null);

async function view(id: string, name: string) {
	const blob = await kl.loadTypePdf(id);
	if (!blob) return;
	closeViewer();
	viewer.value = { id, name, url: URL.createObjectURL(blob) };
}

function closeViewer() {
	if (viewer.value) URL.revokeObjectURL(viewer.value.url);
	viewer.value = null;
}

async function saveCopy(id: string, name: string) {
	const blob = await kl.loadTypePdf(id);
	if (!blob) return;
	if (runningInTauri) {
		const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
		const path = await saveDialog({ defaultPath: name, filters: [{ name: 'PDF', extensions: ['pdf'] }] });
		if (!path) return;
		try {
			await invoke('save_bytes', { path, bytes: Array.from(new Uint8Array(await blob.arrayBuffer())) });
			kl.message = `Saved ${path}`;
		} catch (err) {
			kl.error = String(err);
		}
	} else {
		const url = URL.createObjectURL(blob);
		Object.assign(document.createElement('a'), { href: url, download: name }).click();
		setTimeout(() => URL.revokeObjectURL(url), 10_000);
	}
}

watch(() => [host.value, kl.loadTypes, kl.templateLists], build);
onMounted(() => void kl.loadTemplateLists());
onBeforeUnmount(() => {
	table?.api.destroy();
	closeViewer();
});
</script>

<template>
	<section class="card wizard ref-editor rows-mode key-loads">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Load Types</h2>
			<span class="hint small">{{ items.length }} load type(s). Click a row to edit or delete it.</span>
			<span class="spacer" />
			<HistoryButton entity="load_types" record-id="load-types" label="Load Types" />
			<ListWorkbook list-id="load-types" name="Load Types" />
			<button type="button" @click="open(null)">Add load type</button>
		</div>
		<p v-if="kl.error && !editing" class="error">{{ kl.error }}</p>
		<div class="results mel-grid">
			<div ref="host" class="result-table ref-rows" @click="onClick" />
		</div>

		<AppModal :open="!!editing" :title="editing?.isNew ? 'Add load type' : 'Edit load type'" @close="close">
			<nav v-if="editing" class="subtabs small">
				<button type="button" :class="{ active: tab === 'details' }" @click="tab = 'details'">Details</button>
				<button v-for="l in lists" :key="l.key" type="button" :class="{ active: tab === l.key }" @click="tab = l.key">
					{{ l.name }}<span class="count">{{ editing.form.rows[l.key]?.length ?? 0 }}</span>
				</button>
			</nav>
			<div v-if="editing && list" class="tpl-rows">
				<p class="hint small">
					Every load of this type in the Load List adds these rows to the <strong>{{ list.name }}</strong>. Type <code>&lt;&lt;</code> in a cell
					to pick a tag; it is replaced with that load's data.
					<template v-if="settings.length">A row with <strong>Repeat</strong> = <em>{{ settings[0].values[0] }}</em> is written once for each of the load's power cables, looked up in Cable Types from its Cable Type and Cores cells.</template>
					<span class="tag-help" :title="(kl.templateLists?.tags ?? []).map((t) => `${t.tag}  ${t.meaning}`).join('\n')">All tags ⓘ</span>
				</p>
				<EditGrid :columns="gridCols" :cells="gridCells" :tag-suggestions="tagNames" :cell-class="tagClass"
					:height="Math.min(360, 96 + 26 * Math.max(4, listRows.length))" @set="setCells" @insert="insertRows" @remove="removeRows" />
				<p v-if="!listRows.length" class="hint small">No rows yet: loads of this type add nothing to the {{ list.name }}. Use “+ Row”.</p>
				<p v-for="(msg, k) in kl.fieldErrors" v-show="String(k).startsWith(`${editing.form.id}.rows`)" :key="k" class="warn small">{{ msg }}</p>
			</div>
			<form v-if="editing" v-show="tab === 'details'" class="form-grid two-col" @submit.prevent="save()">
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
				<div class="field pdf-field">
					<span>PDF</span>
					<div class="pdf-box" :class="{ invalid: formErrors.pdf }">
						<template v-if="newPdf">
							<span class="pdf-name">📄 {{ newPdf.name }}</span>
							<span class="hint small">{{ fileSize(newPdf.size) }} · attached when you save</span>
							<span class="spacer" />
							<button type="button" class="secondary small" @click="pdfInput?.click()">Choose another…</button>
							<button type="button" class="secondary small" @click="pdfChange = null; delete formErrors.pdf">Undo</button>
						</template>
						<template v-else-if="editing.pdf && pdfChange !== 'remove'">
							<button type="button" class="link pdf-name" title="Open" @click="view(editing.form.id, editing.pdf.file_name)">📄 {{ editing.pdf.file_name }}</button>
							<span class="hint small">{{ fileSize(editing.pdf.size) }} · {{ editing.pdf.pages }} page(s)</span>
							<span class="spacer" />
							<button type="button" class="secondary small" @click="saveCopy(editing.form.id, editing.pdf.file_name)">Save a copy</button>
							<button type="button" class="secondary small" @click="pdfInput?.click()">Replace…</button>
							<button type="button" class="secondary small" @click="pdfChange = 'remove'">Remove</button>
						</template>
						<template v-else>
							<span class="hint small">{{ pdfChange === 'remove' ? 'The PDF is removed when you save.' : 'No PDF attached.' }}</span>
							<span class="spacer" />
							<button v-if="pdfChange === 'remove'" type="button" class="secondary small" @click="pdfChange = null">Undo</button>
							<button type="button" class="secondary small" @click="pdfInput?.click()">Attach PDF…</button>
						</template>
						<input ref="pdfInput" type="file" accept="application/pdf,.pdf" hidden @change="choosePdf" />
					</div>
					<span v-if="formErrors.pdf" class="warn small">{{ formErrors.pdf }}</span>
				</div>
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

		<AppModal class="pdf-viewer" :open="!!viewer" :title="viewer?.name ?? ''" @close="closeViewer">
			<iframe v-if="viewer" :src="viewer.url" :title="viewer.name" />
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="viewer && saveCopy(viewer.id, viewer.name)">Save a copy</button>
				<button type="button" @click="closeViewer">Close</button>
			</template>
		</AppModal>
	</section>
</template>
