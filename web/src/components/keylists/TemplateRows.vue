<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The predefined rows a load type or an equipment type has for one deliverable list (Cable
// Schedule, Equipment List, Instrument List, PLC I/O List), on a page of their own: a grid whose
// cells can hold <<tags>>, the tags to pick from beside it, and below it what is wrong with the
// tags as typed and the rows filled in from a chosen load (or runsheet row). The parent shows
// the lists' tabs and says which one this is (`list`). Edits go straight into `rows`.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { type ComponentTable, type RowsCheck, type RowsSample, type TemplateRows, modifierText } from '../../lib/keyListTypes';
import { useKeyLists } from '../../stores/keylists';
import EditGrid, { type CellEdit, type GridColumn } from '../common/EditGrid.vue';
import { useUndo } from '../../lib/history';
import TagBrowser from './TagBrowser.vue';
import TypeRowsWorkbook from './TypeRowsWorkbook.vue';

// `id`, `kind`, `name`: whose rows they are. `list`: the key of the list shown.
// `tags`, `paths`: the tags and the linked records' dotted tags to offer (default: a load's, as for a load type).
// `components`: a load type's component tables (their tags are offered and checked).
// `item`: a load type as it is in its form, so one that isn't saved yet can still be filled in.
const props = defineProps<{ rows: TemplateRows; id: string; kind: 'load' | 'equipment'; name: string; list: string; errors?: string[];
	tags?: { tag: string; meaning: string }[]; paths?: { tag: string; meaning: string }[]; components?: ComponentTable[]; item?: unknown }>();
const emit = defineEmits<{
	problems: [counts: Record<string, number>]; // tags with something wrong, per list
	components: [tables: ComponentTable[]]; // an imported workbook's component tables
}>();
const kl = useKeyLists();
// Undo for the grid, across the lists' rows; it starts again when another record's rows are shown.
const hist = useUndo({ get: () => props.rows, resetOn: () => props.id });
onMounted(() => kl.loadTemplateLists());
const lists = computed(() => kl.templateLists?.lists ?? []);
const tagList = computed(() => props.tags ?? kl.templateLists?.tags ?? []);
const pathList = computed(() => props.paths ?? kl.templateLists?.paths ?? []);
const modifiers = computed(() => kl.templateLists?.modifiers ?? []);
// this load type's own component tables are tags too: <<LoadType.CB.PartNumber>>
const tableTags = computed(() => (props.components ?? []).filter((t) => t.name.trim()).flatMap((t) => {
	const n = t.name.replace(/\s+/g, '');
	return [{ tag: `<<LoadType.${n}>>`, meaning: `${t.name}: its row's ${t.columns[0] ?? 'first column'}` },
		...t.columns.map((c) => ({ tag: `<<LoadType.${n}.${c.replace(/\s+/g, '')}>>`, meaning: `${t.name}: ${c}` })),
		{ tag: `<<LoadType.${n}.Min>>`, meaning: `${t.name}: the row's range from` }, { tag: `<<LoadType.${n}.Max>>`, meaning: `${t.name}: the row's range to` }];
}));
const tagNames = computed(() => [...tagList.value, ...tableTags.value, ...pathList.value].map((t) => t.tag));
const modifierNames = computed(() => modifiers.value.map(modifierText));
const cur = computed(() => lists.value.find((l) => l.key === props.list) ?? null);
// (read only here: a list gets its array with its first row, so looking at a type doesn't change it)
const listRows = computed(() => (cur.value ? props.rows[cur.value.key] ?? [] : []));
// A list's row settings (the cable schedule's "Repeat") come first, then its columns.
const settings = computed(() => cur.value?.settings ?? []);
const fields = computed(() => [...settings.value.map((s) => s.name), ...(cur.value?.columns ?? [])]);
const gridCols = computed((): GridColumn[] => [
	...settings.value.map((s): GridColumn => ({ label: s.name, options: s.values, width: 130, badge: 'setting',
		title: `Blank: one row. ${s.values.join(' / ')}: one row for each power cable (parallel cables; single cores and their earth).` })),
	...(cur.value?.columns ?? []).map((c): GridColumn => ({ label: c, width: /Description|Remarks|Code/.test(c) ? 200 : 140 })),
]);
const gridCells = computed(() => listRows.value.map((r) => fields.value.map((c) => r[c] ?? '')));

function setCells(edits: CellEdit[]) {
	for (const e of edits) {
		const row = listRows.value[e.r];
		const field = fields.value[e.c];
		if (!row || !field) continue;
		if (e.value.trim()) row[field] = e.value;
		else delete row[field];
	}
}
function insertRows(at: number, count: number) {
	if (cur.value) (props.rows[cur.value.key] ??= []).splice(at, 0, ...Array.from({ length: count }, () => ({})));
}
/** An imported workbook's rows (and component tables), in place of these lists' rows. */
function replaceRows(rows: TemplateRows, comps: ComponentTable[] | null) {
	for (const [k, v] of Object.entries(rows)) props.rows[k] = v;
	if (comps) emit('components', comps);
}
function removeRows(idx: number[]) {
	if (!cur.value) return;
	const drop = new Set(idx);
	props.rows[cur.value.key] = listRows.value.filter((_, i) => !drop.has(i));
}

// -- picking a tag ----------------------------------------------------------------------
const grid = ref<InstanceType<typeof EditGrid> | null>(null);
const pickNote = ref('');
function pick(text: string) {
	pickNote.value = grid.value?.insertText(text) ? '' : text.startsWith('|') ? 'Put a tag in the cell first: a modifier goes on a tag.' : 'Select a cell first.';
}

// -- checking the tags, and the rows filled in ------------------------------------------
const samples = ref<RowsSample[]>([]);
const sample = ref('');
const check = ref<RowsCheck | null>(null);
const checking = ref(false);
async function loadSamples() {
	samples.value = await kl.templateSamples(props.kind, props.id);
	if (!samples.value.some((s) => s.ref === sample.value)) sample.value = samples.value.find((s) => s.own)?.ref ?? '';
}
onMounted(loadSamples);
watch(() => props.id, () => { check.value = null; sample.value = ''; void loadSamples(); });
const own = computed(() => samples.value.filter((s) => s.own));
const others = computed(() => samples.value.filter((s) => !s.own));
const sampleLabel = (s: RowsSample) => (s.description ? `${s.tag} · ${s.description}` : s.tag);

let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0;
async function runCheck() {
	const mine = ++seq;
	checking.value = true;
	const got = await kl.checkTemplateRows({ kind: props.kind, id: props.id, rows: props.rows, components: props.components ?? [], item: props.item,
		name: props.name, sample: sample.value || null });
	if (mine !== seq) return; // an older answer: a newer check is on its way
	checking.value = false;
	if (!got) return;
	check.value = got;
	emit('problems', Object.fromEntries(Object.entries(got.problems).map(([k, v]) => [k, v.length])));
}
// whatever the answer depends on, as text: a change in it asks again, a moment after the last keystroke
const asked = computed(() => JSON.stringify([props.id, props.rows, props.components ?? [], props.item ?? null, props.name, sample.value]));
watch(asked, () => {
	clearTimeout(timer);
	timer = setTimeout(() => void runCheck(), 400);
}, { immediate: true });
onBeforeUnmount(() => clearTimeout(timer));

const problems = computed(() => (cur.value ? check.value?.problems[cur.value.key] ?? [] : []));
const byCell = computed(() => {
	const out = new Map<string, string[]>();
	for (const p of problems.value) {
		const k = `${p.row}|${p.column}`;
		out.set(k, [...(out.get(k) ?? []), `${p.tag}: ${p.problem}`]);
	}
	return out;
});
const cellProblems = (r: number, c: number) => byCell.value.get(`${r}|${fields.value[c]}`);
const cellClass = (r: number, c: number) => (cellProblems(r, c) ? 'bad-tag' : /<<[^<>]+>>/.test(gridCells.value[r]?.[c] ?? '') ? 'has-tag' : '');
const cellTitle = (r: number, c: number) => cellProblems(r, c)?.join('\n');
const goTo = (row: number, column: string) => grid.value?.select(row, Math.max(0, fields.value.indexOf(column)));

const preview = computed(() => (cur.value ? check.value?.preview?.[cur.value.key] ?? null : null));
const chosen = computed(() => samples.value.find((s) => s.ref === sample.value) ?? null);
const cellText = (v: string | number | boolean | null) => (v === null || v === undefined ? '' : String(v));
const unfilled = (v: string | number | boolean | null) => /<<[^<>]+>>/.test(cellText(v));
/** The filled-in rows, each with its template row's number; a row that makes several (one per cable) numbers them. */
const previewRows = computed(() => {
	const rows = preview.value?.rows ?? [];
	const made = new Map<number, number>();
	for (const r of rows) made.set(r.template_row, (made.get(r.template_row) ?? 0) + 1);
	const nth = new Map<number, number>();
	return rows.map((r) => {
		const n = (nth.get(r.template_row) ?? 0) + 1;
		nth.set(r.template_row, n);
		return { ...r, label: (made.get(r.template_row) ?? 1) > 1 ? `${r.template_row + 1}.${n}` : `${r.template_row + 1}` };
	});
});
const what = computed(() => (props.kind === 'load' ? 'load' : 'runsheet row'));
</script>

<template>
	<div class="tpl-rows tpl-page">
		<div class="tpl-main">
			<div class="row tight tpl-top">
				<p class="hint small">
					<slot :list="cur" />
					Type <code>&lt;&lt;</code> in a cell to pick a tag, or click one in the list on the right. A <code>.</code> follows a link
					(<code>&lt;&lt;LoadType.Name&gt;&gt;</code>), a <code>|</code> changes the text (<code>&lt;&lt;Tag|upper&gt;&gt;</code>).
				</p>
				<TypeRowsWorkbook :name="name" :kind="kind" :rows="rows" :components="components" @replace="replaceRows" />
			</div>
			<EditGrid ref="grid" :columns="gridCols" :cells="gridCells" :history="hist" :tag-suggestions="tagNames" :modifier-suggestions="modifierNames"
				:cell-class="cellClass" :cell-title="cellTitle" @set="setCells" @insert="insertRows" @remove="removeRows" />
			<p v-if="pickNote" class="warn small">{{ pickNote }}</p>
			<p v-for="m in errors ?? []" :key="m" class="warn small">{{ m }}</p>

			<section class="tpl-check" aria-label="Check and preview">
				<div class="row tight tpl-check-head">
					<strong>Check</strong>
					<span v-if="!check" class="hint small">Checking…</span>
					<span v-else-if="problems.length" class="warn small">⚠ {{ problems.length }} tag(s) in these rows match nothing</span>
					<span v-else class="saved">✓ Every tag in these rows is one the {{ what }} has</span>
					<span class="spacer" />
					<label class="row tight tpl-sample">
						<span class="hint small">Fill in from</span>
						<select v-model="sample" :aria-label="`The ${what} to fill the rows in from`">
							<option value="">— no preview —</option>
							<optgroup v-if="own.length" :label="kind === 'load' ? 'Loads of this type' : 'Runsheet rows of this type'">
								<option v-for="s in own" :key="s.ref" :value="s.ref">{{ sampleLabel(s) }}</option>
							</optgroup>
							<optgroup v-if="others.length" :label="kind === 'load' ? 'Other loads (filled in as if of this type)' : 'Other runsheet rows (as if of this type)'">
								<option v-for="s in others" :key="s.ref" :value="s.ref">{{ sampleLabel(s) }}</option>
							</optgroup>
						</select>
					</label>
				</div>
				<ul v-if="problems.length" class="tpl-problems">
					<li v-for="(p, i) in problems" :key="i">
						<button type="button" class="link" :title="`Go to row ${p.row + 1}, ${p.column}`" @click="goTo(p.row, p.column)">Row {{ p.row + 1 }}, {{ p.column }}</button>
						<code>{{ p.tag }}</code> <span>{{ p.problem }}</span>
					</li>
				</ul>
				<template v-if="sample">
					<p v-for="n in check?.notes ?? []" :key="n" class="hint small">{{ n }}</p>
					<div v-if="preview && previewRows.length" class="tpl-preview" :class="{ stale: checking }">
						<table class="grid simple">
							<thead><tr><th class="num" title="The template row it comes from">Row</th><th v-for="h in preview.header" :key="h">{{ h }}</th></tr></thead>
							<tbody>
								<tr v-for="(r, i) in previewRows" :key="i">
									<td class="num"><button type="button" class="link" title="Go to this template row" @click="goTo(r.template_row, fields[0])">{{ r.label }}</button></td>
									<td v-for="(v, c) in r.cells" :key="c" :class="{ unfilled: unfilled(v) }"
										:title="unfilled(v) ? 'A tag here matched nothing and is left as typed' : undefined">{{ cellText(v) }}</td>
								</tr>
							</tbody>
						</table>
					</div>
					<p v-else-if="preview" class="hint small">
						{{ listRows.length ? `These rows add nothing to the ${cur?.name} for ${chosen?.tag}.` : `No rows yet for the ${cur?.name}. Use “+ Row”.` }}
					</p>
				</template>
				<p v-else class="hint small">
					{{ samples.length ? `Choose a ${what} to see these rows as they will be written for it.`
						: kind === 'load' ? 'There are no loads in the Load List yet to fill these rows in from.' : 'There are no rows in the Instrument Runsheet yet to fill these rows in from.' }}
				</p>
			</section>
		</div>
		<TagBrowser :tags="tagList" :paths="pathList" :tables="tableTags" :modifiers="modifiers"
			:what="kind === 'load' ? 'The load' : 'The runsheet row'" @pick="pick" />
	</div>
</template>
