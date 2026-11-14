<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// One load type, on a page of its own (in place of the Load Types grid): its details, its
// predefined rows for each deliverable list (a tab per list: every load of the type in the
// Load List produces those rows, with the <<tags>> filled in from it) and its component tables.
// Nothing is saved until Save.
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import {
	PHASES, RATING_UNITS, type AttachedFile, type ComponentTable, type LoadType, type LoadTypeField, type LoadTypeForm, copyName, fileSize, loadTypeProblems,
} from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import ComponentTablesEditor from './ComponentTablesEditor.vue';
import TemplateRows from './TemplateRows.vue';

// `row`: the load type to edit (null: a new one). `starters`: the Starter Coordination charts, for the Starter chart choice.
const props = defineProps<{ row: LoadType | null; starters: { charts: string[]; default_chart: string } }>();
const emit = defineEmits<{
	close: [];
	view: [id: string, name: string]; // open the attached PDF
	copy: [id: string, name: string]; // save a copy of it
}>();
const kl = useKeyLists();
const items = computed(() => kl.loadTypes?.items ?? []);

type Kind = 'text' | 'choice' | 'whole' | 'decimal' | 'yesno' | 'starter';
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
	{ field: 'starter_chart', label: 'Starter chart', kind: 'starter' },
	{ field: 'multi_load', label: 'Multi load', kind: 'yesno' },
];
const text = (v: string | number | null | undefined) => (v === null || v === undefined ? '' : String(v));
const formOf = (row: LoadType | null): LoadTypeForm => ({
	id: row?.id ?? newId(), code: row?.code ?? '', name: row?.name ?? '', rating_unit: row?.rating_unit ?? '',
	voltage: text(row?.voltage), phases: row?.phases ?? '', from_value: text(row?.from_value), to_value: text(row?.to_value),
	std_drg: row?.std_drg ?? '', bucket_type: row?.bucket_type ?? '', load_type: row?.load_type ?? '',
	field_options: row?.field_options ?? '', multi_load: row?.multi_load ?? false, load_qty: text(row?.load_qty),
	starter_chart: row?.starter_chart ?? '',
	rows: JSON.parse(JSON.stringify(row?.rows ?? {})),
	components: JSON.parse(JSON.stringify(row?.components ?? [])),
});
/** The form as it would be saved, as text: rows left blank and lists left empty don't count as a change. */
const asSaved = (f: LoadTypeForm) => JSON.stringify({ ...f,
	rows: Object.fromEntries(Object.entries(f.rows).map(([k, v]) => [k, v.filter((r) => Object.keys(r).length)] as const).filter(([, v]) => v.length)) });

const isNew = ref(!props.row);
const form = ref<LoadTypeForm>(formOf(props.row));
const pdf = ref<AttachedFile | null>(props.row?.pdf ?? null);
const saved = ref(asSaved(form.value));
// The page's tab: 'details', the key of a deliverable list, or 'components'.
const tab = ref('details');
const lists = computed(() => kl.templateLists?.lists ?? []);
const onList = computed(() => lists.value.some((l) => l.key === tab.value));
const tagProblems = ref<Record<string, number>>({});
// the details, without the rows and tables: what a load type that isn't saved yet is filled in with
const details = computed(() => Object.fromEntries(Object.entries(form.value).filter(([k]) => k !== 'rows' && k !== 'components')));

// A PDF chosen in the form, or 'remove': applied when the load type is saved.
const pdfChange = ref<File | 'remove' | null>(null);
const pdfInput = ref<HTMLInputElement | null>(null);
const newPdf = computed(() => (pdfChange.value instanceof File ? pdfChange.value : null));
const MAX_PDF = 50 * 1024 * 1024;
const formErrors = ref<Partial<Record<LoadTypeField | 'pdf', string>>>({});
const savedNote = ref('');

const dirty = computed(() => pdfChange.value !== null || asSaved(form.value) !== saved.value);
watch(dirty, (d) => { kl.loadTypeDirty = d; }, { immediate: true });
watch(form, () => { savedNote.value = ''; }, { deep: true });
onBeforeUnmount(() => { kl.loadTypeDirty = false; });

const title = computed(() => [form.value.code, form.value.name].filter((s) => s.trim()).join(' · ') || 'New load type');
const rowErrors = computed(() => Object.entries(kl.fieldErrors).filter(([k]) => k.startsWith(`${form.value.id}.rows`)).map(([, m]) => m));

function back() {
	if (dirty.value && !confirm(isNew.value ? 'Leave without saving this new load type?' : `Leave without saving the changes to "${form.value.code}"?`)) return;
	kl.error = null;
	emit('close');
}

/** A new load type with this one's details, rows (as they are on the page) and PDF: saved with Save. */
async function clone() {
	const from = form.value.id;
	const file = pdfChange.value === 'remove' ? null : pdfChange.value instanceof File ? pdfChange.value : pdf.value;
	formErrors.value = {};
	kl.error = null;
	// the code is kept (load types can share one): the copy needs its own range before it can be saved
	form.value = { ...JSON.parse(JSON.stringify(form.value)), id: newId(), name: copyName(form.value.name, items.value.map((r) => r.name), 'name') };
	isNew.value = true;
	pdf.value = null;
	pdfChange.value = null;
	tab.value = 'details';
	if (file instanceof File) pdfChange.value = file;
	else if (file) {
		const blob = await kl.loadTypePdf(from);
		if (blob) pdfChange.value = new File([blob], file.file_name, { type: 'application/pdf' });
	}
	await nextTick();
	const code = document.querySelector<HTMLInputElement>('.lt-page .form-grid input[type="text"]');
	code?.focus();
	code?.select();
}

async function save(then: 'stay' | 'close' | 'another' = 'stay') {
	const f = form.value;
	formErrors.value = loadTypeProblems(f, items.value.filter((r) => r.id !== f.id));
	if (Object.keys(formErrors.value).length) {
		tab.value = 'details';
		return;
	}
	if (pdfChange.value instanceof File) {
		const file = pdfChange.value;
		if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') formErrors.value.pdf = 'Choose a PDF file';
		else if (file.size > MAX_PDF) formErrors.value.pdf = 'The file is larger than 50 MB';
		if (formErrors.value.pdf) {
			tab.value = 'details';
			return;
		}
	}
	if (!(await kl.saveLoadType(f))) {
		// The engine names problems as "<row id>.<field>"; show this row's beside its inputs, or open the list they are in.
		const mine: Partial<Record<LoadTypeField, string>> = {};
		let where = '';
		for (const [k, msg] of Object.entries(kl.fieldErrors)) {
			if (!k.startsWith(`${f.id}.`)) continue;
			const field = k.slice(f.id.length + 1);
			if (field.startsWith('rows')) where ||= field.split('.')[1] ?? '';
			else if (field.startsWith('components')) where ||= 'components';
			else mine[field as LoadTypeField] = msg;
		}
		formErrors.value = mine;
		if (Object.keys(mine).length) tab.value = 'details';
		else if (where) tab.value = where;
		return;
	}
	// The row is saved now; then the PDF (it can only be attached to a saved row).
	isNew.value = false;
	saved.value = asSaved(f);
	const change = pdfChange.value;
	if (change instanceof File ? !(await kl.attachLoadTypePdf(f.id, change)) : change === 'remove' && !(await kl.removeLoadTypePdf(f.id))) {
		formErrors.value = { pdf: `The load type was saved, but not the PDF change: ${kl.error}` };
		kl.error = null;
		tab.value = 'details';
		return;
	}
	pdfChange.value = null;
	pdf.value = items.value.find((r) => r.id === f.id)?.pdf ?? null;
	if (then === 'close') emit('close');
	else if (then === 'another') {
		form.value = formOf(null);
		saved.value = asSaved(form.value);
		isNew.value = true;
		pdf.value = null;
		tab.value = 'details';
		await nextTick();
		document.querySelector<HTMLInputElement>('.lt-page .form-grid input[type="text"]')?.focus();
	} else {
		await nextTick(); // (the form's own watcher has cleared the note by now)
		savedNote.value = 'Saved';
	}
}

function choosePdf(ev: Event) {
	const input = ev.target as HTMLInputElement;
	const f = input.files?.[0];
	input.value = ''; // choosing the same file again still counts
	if (!f) return;
	pdfChange.value = f;
	delete formErrors.value.pdf;
}

async function remove() {
	if (isNew.value || !confirm(`Delete the load type "${form.value.code}"?`)) return;
	if (await kl.deleteLoadType(form.value.id)) emit('close');
}
const setComponents = (tables: ComponentTable[]) => { form.value.components = tables; };
</script>

<template>
	<div class="lt-page type-page">
		<div class="mel-head">
			<button type="button" class="link back" @click="back">‹ Load Types</button>
			<h2 class="key-title">{{ title }}</h2>
			<span v-if="isNew" class="kind">New</span>
			<span class="spacer" />
			<span v-if="dirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="savedNote" class="saved">✓ {{ savedNote }}</span>
			<button v-if="!isNew" type="button" class="secondary" :disabled="kl.busy" @click="remove">Delete</button>
			<button v-if="!isNew" type="button" class="secondary" :disabled="kl.busy"
				title="A new load type with this one's details, rows and PDF (saved when you Save)" @click="clone">Clone</button>
			<button v-if="isNew" type="button" class="secondary" :disabled="kl.busy" @click="save('another')">Save and add another</button>
			<button type="button" class="secondary" :disabled="kl.busy || !dirty" @click="save('close')">Save and close</button>
			<button type="button" :disabled="kl.busy || !dirty" @click="save()">Save</button>
		</div>
		<p v-if="kl.error" class="error">{{ kl.error }}</p>
		<nav class="subtabs">
			<button type="button" :class="{ active: tab === 'details' }" @click="tab = 'details'">
				Details<span v-if="Object.keys(formErrors).length" class="count bad" title="Something in the details needs fixing">⚠</span>
			</button>
			<button v-for="l in lists" :key="l.key" type="button" :class="{ active: tab === l.key }" @click="tab = l.key">
				{{ l.name }}<span class="count">{{ form.rows[l.key]?.length ?? 0 }}</span>
				<span v-if="tagProblems[l.key]" class="count bad" :title="`${tagProblems[l.key]} tag(s) in these rows match nothing`">⚠ {{ tagProblems[l.key] }}</span>
			</button>
			<button type="button" :class="{ active: tab === 'components' }" title="Parts per range of the load's rating, for <<LoadType.CB.PartNumber>>"
				@click="tab = 'components'">Components<span class="count">{{ form.components.length }}</span></button>
		</nav>

		<!-- kept while another tab shows, so its check, its undo and the chosen load stay -->
		<TemplateRows v-show="onList" :id="form.id" :rows="form.rows" kind="load" :name="form.code || 'load type'" :list="onList ? tab : ''"
			:components="form.components" :item="details" :errors="rowErrors" @problems="tagProblems = $event" @components="setComponents">
			<template #default="{ list }">
				Every load of this type in the Load List adds these rows to the <strong>{{ list?.name }}</strong>, with each tag replaced by that load's data.
				<template v-if="list?.settings.length">A row with <strong>Repeat</strong> = <em>{{ list.settings[0].values[0] }}</em> is written once for each of the
					load's power cables, looked up in Cable Types from its Cable Type and Cores cells.</template>
			</template>
		</TemplateRows>

		<div v-if="tab === 'components'" class="type-scroll">
			<ComponentTablesEditor :tables="form.components" :errors="kl.fieldErrors" :form-id="form.id" />
		</div>

		<div v-show="tab === 'details'" class="type-scroll">
			<form class="form-grid two-col" @submit.prevent="save()">
				<label v-for="c in COLS" :key="c.field" class="field" :class="{ check: c.kind === 'yesno' }">
					<template v-if="c.kind === 'yesno'">
						<input v-model="form.multi_load" type="checkbox" /><span>{{ c.label }}</span>
					</template>
					<template v-else>
						<span>{{ c.label }}<span v-if="c.required" class="req"> *</span></span>
						<select v-if="c.kind === 'starter'" v-model="form.starter_chart" :class="{ invalid: formErrors[c.field] }"
							title="Starter Coordination chart for this type's loads: <<Starter.CB>>, <<Starter.Contactor>>…">
							<option value="">Project default{{ starters.default_chart ? ` (${starters.default_chart})` : '' }}</option>
							<option v-for="o in starters.charts" :key="o" :value="o">{{ o }}</option>
							<option value="None">None (no starter)</option>
							<option v-if="form.starter_chart && form.starter_chart !== 'None' && !starters.charts.includes(form.starter_chart)"
								:value="form.starter_chart">{{ form.starter_chart }} (not in the list)</option>
						</select>
						<select v-else-if="c.kind === 'choice'" v-model="form[c.field]" :class="{ invalid: formErrors[c.field] }">
							<option value="">—</option>
							<option v-for="o in c.options" :key="o" :value="o">{{ o }}</option>
						</select>
						<input v-else v-model="(form[c.field] as string)" type="text" :placeholder="c.hint"
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
						<template v-else-if="pdf && pdfChange !== 'remove'">
							<button type="button" class="link pdf-name" title="Open" @click="emit('view', form.id, pdf.file_name)">📄 {{ pdf.file_name }}</button>
							<span class="hint small">{{ fileSize(pdf.size) }} · {{ pdf.pages }} page(s)</span>
							<span class="spacer" />
							<button type="button" class="secondary small" @click="emit('copy', form.id, pdf.file_name)">Save a copy</button>
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
			<p class="hint small lt-next">
				The rows this load type adds to each list are on the tabs above: <strong>{{ lists.map((l) => l.name).join(', ') }}</strong>.
			</p>
		</div>
	</div>
</template>
