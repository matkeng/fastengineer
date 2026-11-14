<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { PANEL_TYPE, type Changes, type RevisionInfo } from '../../lib/deliverableTypes';
import { type BuildResult, type OutputRow, type Scalar, cellText } from '../../lib/genTypes';
import { useDeliverables } from '../../stores/deliverables';
import { useGenerators } from '../../stores/generators';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import HistoryButton from '../audit/HistoryButton.vue';
import AppModal from '../common/AppModal.vue';

// Deliverables: the lists a project issues. Each takes its content from the Project Master Load List
// (generated on the spot from the load types' rows) or from a generator's builds,
// and is issued in lettered revisions (A, B, ...), frozen when the user issues them.
const dl = useDeliverables();
const gens = useGenerators();
const kl = useKeyLists();
const ui = useUi();

const types = computed(() => dl.overview?.types ?? []);
const generators = computed(() => dl.overview?.generators ?? []);
const groups = computed(() => types.value.map((t) => ({ type: t, items: (dl.overview?.deliverables ?? []).filter((s) => s.deliverable.type === t) })));
const d = computed(() => dl.detail);
const cur = computed(() => d.value?.current ?? null);
const PROJECT = '@project'; // the source drop-down's value for the project's own content
// What a deliverable of a type is made from in the project: its Project Master list (both generators), or the Load List.
const MASTERS: Record<string, string> = { 'Cable Schedule': 'Project Master Cable Schedule', 'Equipment List': 'Project Master Equipment List',
	'Instrument List': 'Project Master Instrument List', 'PLC I/O List': 'Project Master IO List' };
const projectName = (type: string | undefined) => MASTERS[type ?? ''] ?? 'Project Master Load List';
const isProject = computed(() => d.value?.deliverable.source === 'project');
const isPanel = computed(() => d.value?.deliverable.source === 'panel');
const panels = computed(() => dl.overview?.panels ?? []);
// a Distribution Panel is only ever a panel's schedule, and nothing else is: the type isn't changed afterwards
const typeChoices = computed(() => (dl.form?.type === PANEL_TYPE ? [PANEL_TYPE] : types.value.filter((t) => t !== PANEL_TYPE)));
const columns = computed(() => {
	const f = dl.form;
	if (!f) return [];
	return f.source !== 'generator' ? dl.overview?.project_columns[f.type] ?? [] : generators.value.find((g) => g.id === f.generator_id)?.columns ?? [];
});
const source = computed({
	get: () => (dl.form?.source === 'project' ? PROJECT : dl.form?.generator_id ?? ''),
	set: (v: string) => {
		if (!dl.form) return;
		dl.form.source = v === PROJECT ? 'project' : 'generator';
		dl.form.generator_id = v === PROJECT ? '' : v;
		if (!columns.value.includes(dl.form.filter_column)) dl.form.filter_column = '';
		dl.form.columns = dl.form.columns.filter((c) => columns.value.includes(c));
	},
});

// -- which columns, in which order ------------------------------------------------------------
// The dialog works on a copy: every column of the content, the kept ones first in their order.
const picking = ref<{ name: string; on: boolean }[] | null>(null);
const columnsSummary = computed(() => {
	const f = dl.form;
	if (!f || !f.columns.length) return `All ${columns.value.length} columns`;
	return `${f.columns.length} of ${columns.value.length}: ${f.columns.join(', ')}`;
});
function startColumns() {
	const f = dl.form;
	if (!f) return;
	const kept = f.columns.filter((c) => columns.value.includes(c));
	picking.value = kept.length
		? [...kept.map((name) => ({ name, on: true })), ...columns.value.filter((c) => !kept.includes(c)).map((name) => ({ name, on: false }))]
		: columns.value.map((name) => ({ name, on: true }));
}
function moveColumn(i: number, by: -1 | 1) {
	const list = picking.value;
	if (!list || i + by < 0 || i + by >= list.length) return;
	[list[i], list[i + by]] = [list[i + by], list[i]];
}
const setAllColumns = (on: boolean) => picking.value?.forEach((c) => { c.on = on; });
function resetColumns() {
	picking.value = columns.value.map((name) => ({ name, on: true }));
}
function applyColumns() {
	const list = picking.value;
	if (!list || !dl.form) return;
	const chosen = list.filter((c) => c.on).map((c) => c.name);
	// every column in the content's own order is the same as not choosing: new columns then show too
	dl.form.columns = chosen.length === columns.value.length && chosen.every((c, i) => c === columns.value[i]) ? [] : chosen;
	picking.value = null;
}
const when = (iso: string) => new Date(iso).toLocaleString();
/** A distribution panel's header block: of the revision shown, else as it is now. */
const summary = computed(() => (dl.shown ? dl.shown.summary ?? [] : cur.value?.summary ?? []).filter(([, v]) => v !== null && v !== ''));

onMounted(() => dl.refresh());
watch(() => ui.tab, async (tab) => {
	if (tab !== 'deliverables') return;
	await dl.refresh();
	if (d.value && !dl.dirty) await dl.open(d.value.deliverable.id); // the generator may have been built since
});

async function select(id: string) {
	if (dl.dirty && !confirm('Discard unsaved changes to this deliverable?')) return;
	await dl.open(id);
}

// -- new deliverable ----------------------------------------------------------------------
const adding = ref<{ type: string; name: string; generator_id: string; panel_id: string } | null>(null);
function startAdd(type?: string) {
	dl.error = null;
	adding.value = { type: type ?? types.value[0] ?? '', name: '', generator_id: PROJECT, panel_id: panels.value[0]?.id ?? '' };
}
async function add() {
	const a = adding.value;
	if (!a) return;
	if (dl.dirty && !confirm('Discard unsaved changes to the open deliverable?')) return;
	const made = a.type === PANEL_TYPE ? dl.create(a.type, a.name, null, a.panel_id) : dl.create(a.type, a.name, a.generator_id === PROJECT ? null : a.generator_id);
	if (await made) adding.value = null;
}

async function remove() {
	if (d.value && confirm(`Delete the deliverable "${d.value.deliverable.name}"?`)) await dl.remove();
}

// -- issue, amend, withdraw ------------------------------------------------------------------
const issuing = ref<{ description: string; build_id: string } | null>(null);
function startIssue() {
	dl.error = null;
	issuing.value = { description: '', build_id: '' };
}
async function issue() {
	const i = issuing.value;
	if (i && (await dl.issue(i.description, i.build_id || null))) issuing.value = null;
}
const pending = (c: Changes | null) => (c ? `${c.added} added · ${c.removed} removed · ${c.changed} changed` : '');
const nothingNew = computed(() => !!cur.value?.changes && !cur.value.changes.added && !cur.value.changes.removed && !cur.value.changes.changed);

const withdrawing = ref<{ rev: RevisionInfo; reason: string } | null>(null);
async function withdraw() {
	const w = withdrawing.value;
	if (w && (await dl.withdraw(w.rev, w.reason))) withdrawing.value = null;
}
async function amend(rev: RevisionInfo) {
	const text = prompt(`Description of Rev ${rev.letter}:`, rev.description);
	if (text !== null && text !== rev.description) await dl.amend(rev, text);
}

function openMaster() {
	const key = { 'Cable Schedule': 'cable_schedule', 'Equipment List': 'equipment_list', 'Instrument List': 'instrument_list', 'PLC I/O List': 'plc_io_list' }[d.value?.deliverable.type ?? ''];
	if (key) kl.masterKey = key;
	void kl.select('master');
	ui.go('keylists');
}

function openKeyList(id: 'load-list' | 'load-types' | 'distribution-panels') {
	if (id === 'distribution-panels') kl.panelSelected = d.value?.deliverable.panel_id || kl.panelSelected;
	void kl.select(id);
	ui.go('keylists');
}

async function openGenerator() {
	const id = d.value?.deliverable.generator_id;
	if (!id) return;
	if (gens.draft?.id !== id) await gens.open(id);
	gens.tab = 'build';
	ui.go('generators');
}

// -- the content shown: the current state, or an issued revision -----------------------------
const view = ref<'rows' | 'changes'>('rows');
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<unknown> | null = null;
const content = computed<{ result: BuildResult | null; changes: Changes | null; key: string; title: string }>(() => {
	if (dl.shown) {
		return { result: dl.shown.result, changes: dl.compared?.changes ?? dl.shown.changes, key: dl.shown.diff_key, title: `Rev ${dl.shown.info.letter}` };
	}
	return { result: cur.value?.result ?? null, changes: cur.value?.changes ?? null, key: '', title: 'Current (not issued)' };
});

// Comparing the viewed revision with any other one ('' = the one before it), and whether an
// Excel export gets a Changes sheet (against the same revision when it is the one being viewed).
const against = ref('');
const withChanges = ref(false);
const others = computed(() => (d.value?.revisions ?? []).filter((r) => r.id !== dl.shown?.info.id));
watch(() => dl.shown?.info.id, () => { against.value = ''; });
async function pickAgainst() {
	await dl.compareWith(against.value || null);
	if (against.value && !dl.compared) against.value = '';
	if (content.value.changes) view.value = 'changes';
}
function exportExcel(r: RevisionInfo) {
	const other = dl.shown?.info.id === r.id && against.value ? against.value : 'previous';
	void dl.exportRevision(r, 'xlsx', withChanges.value ? other : null);
}
const comparedText = computed(() => {
	if (!dl.shown) return 'What a new revision would contain; changes are against the latest revision.';
	const issued = `As issued on ${when(dl.shown.info.issued_at)}`;
	return dl.compared ? `${issued}; changes are from Rev ${dl.compared.old.letter} to Rev ${dl.compared.new.letter}.` : `${issued}; changes are against the revision before it.`;
});

interface ChangeLine { kind: string; key: string; column: string; old: Scalar; new: Scalar }
const changeLines = computed<ChangeLine[]>(() => {
	const out: ChangeLine[] = [];
	for (const e of content.value.changes?.entries ?? []) {
		if (e.kind !== 'changed') out.push({ kind: e.kind, key: e.key, column: '', old: null, new: null });
		else for (const c of e.cells) out.push({ kind: 'changed', key: e.key, column: c.column, old: c.old, new: c.new });
	}
	return out;
});
const render = (v: Scalar) => escapeHtml(cellText(v));

function draw() {
	table?.api.destroy();
	table = null;
	if (!host.value) return;
	host.value.replaceChildren();
	const r = content.value.result;
	if (view.value === 'rows' && r) {
		const cols: ColumnsConfig[] = r.header.map((h, i) => ({
			title: escapeHtml(h),
			data: (row: OutputRow) => row.cells[i] ?? null,
			render: (v: Scalar, type: string) => (type === 'display' ? render(v) : cellText(v)),
		}));
		table = createFilteredTable<OutputRow>(host.value, cols.length, {
			data: r.rows,
			columns: cols,
			ordering: false, // keep the build order
			pageLength: 100,
			lengthMenu: [50, 100, 500, 2000],
			layout: TOOLBAR_LAYOUT,
			buttons: [{ extend: 'colvis', text: 'Columns' }],
			language: { search: 'Search all:', emptyTable: 'No rows.' },
			createdRow: (tr: HTMLTableRowElement, data: unknown) => tr.classList.toggle('sep-row', (data as OutputRow).run_row_id === null),
		}) as FilteredTable<unknown>;
	} else if (view.value === 'changes' && content.value.changes) {
		const cols: ColumnsConfig[] = [
			{ title: 'Change', data: 'kind', render: (v: string, t: string) => (t === 'display' ? `<span class="chg chg-${v}">${v}</span>` : v) },
			{ title: 'Key', data: 'key', className: 'key-col', render: (v: string) => escapeHtml(v) },
			{ title: 'Column', data: 'column', render: (v: string) => escapeHtml(v) },
			{ title: 'Old', data: 'old', render: (v: Scalar) => render(v) },
			{ title: 'New', data: 'new', render: (v: Scalar) => render(v) },
		];
		table = createFilteredTable<ChangeLine>(host.value, cols.length, {
			data: changeLines.value, columns: cols, pageLength: 100, layout: TOOLBAR_LAYOUT, buttons: [],
			language: { search: 'Search all:', emptyTable: 'No changes.' },
		}, {
			0: {
				options: [{ value: '', label: 'All' }, { value: 'added', label: 'Added' }, { value: 'removed', label: 'Removed' }, { value: 'changed', label: 'Changed' }],
				test: (v, row) => !v || row.kind === v,
			},
		}) as FilteredTable<unknown>;
	}
}
watch([content, view, host], () => void nextTick(draw));
watch(content, (c) => { if (view.value === 'changes' && !c.changes) view.value = 'rows'; });
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<div class="ref deliverables">
		<div class="ref-layout">
			<aside class="card ref-side">
				<section v-for="g in groups" :key="g.type">
					<h3>{{ g.type }}s</h3>
					<ul class="ref-nav">
						<li v-for="s in g.items" :key="s.deliverable.id" :class="{ current: d?.deliverable.id === s.deliverable.id }"
							:title="s.deliverable.doc_number" @click="select(s.deliverable.id)">
							<span class="name">{{ s.deliverable.name }}</span>
							<span class="count" :class="{ none: !s.latest }" :title="s.latest ? `Rev ${s.latest.letter}, ${when(s.latest.issued_at)}` : 'Not issued yet'">{{ s.latest ? `Rev ${s.latest.letter}` : '–' }}</span>
						</li>
						<li v-if="!g.items.length" class="none-yet hint">None yet</li>
					</ul>
					<button type="button" class="secondary small" @click="startAdd(g.type)">+ {{ g.type }}</button>
				</section>
			</aside>

			<section v-if="d && dl.form" class="card wizard ref-editor dl-editor">
				<div class="mel-head">
					<span class="kind tree">{{ d.deliverable.type }}</span>
					<h2 class="key-title">{{ d.deliverable.name }}</h2>
					<span class="spacer" />
					<span v-if="dl.dirty" class="unsaved">● Unsaved changes</span>
					<span v-else-if="dl.message" class="saved">✓ {{ dl.message }}</span>
					<HistoryButton entity="deliverable" :record-id="d.deliverable.id" :label="d.deliverable.name" />
					<button type="button" class="secondary" :disabled="!dl.dirty || dl.busy" @click="dl.discard()">Discard</button>
					<button type="button" :disabled="!dl.dirty || dl.busy" @click="dl.save()">Save</button>
				</div>
				<p v-if="dl.error && !issuing && !withdrawing && !adding" class="error">{{ dl.error }}</p>

				<div class="dl-fields">
					<label class="field"><span>Name<span class="req"> *</span></span>
						<input v-model="dl.form.name" :class="{ invalid: dl.fieldErrors.name }" />
						<span v-if="dl.fieldErrors.name" class="warn small">{{ dl.fieldErrors.name }}</span></label>
					<label class="field"><span>Type</span>
						<select v-model="dl.form.type" :disabled="isPanel"><option v-for="t in typeChoices" :key="t" :value="t">{{ t }}</option></select></label>
					<label class="field"><span>Document number</span><input v-model="dl.form.doc_number" class="mono" /></label>
					<label class="field"><span>Document title</span><input v-model="dl.form.doc_title" /></label>
					<label v-if="dl.form.source === 'panel'" class="field"><span>Distribution panel<span class="req"> *</span></span>
						<select v-model="dl.form.panel_id" :class="{ invalid: dl.fieldErrors.panel_id }">
							<option v-for="p in panels" :key="p.id" :value="p.id">{{ p.tag }}{{ p.title ? ` – ${p.title}` : '' }}</option>
						</select>
						<span v-if="dl.fieldErrors.panel_id" class="warn small">{{ dl.fieldErrors.panel_id }}</span></label>
					<label v-else class="field"><span>Content from<span class="req"> *</span></span>
						<select v-model="source" :class="{ invalid: dl.fieldErrors.generator_id }">
							<option :value="PROJECT">{{ projectName(dl.form.type) }}</option>
							<optgroup v-if="generators.length" label="Generators from imported workbooks">
								<option v-for="g in generators" :key="g.id" :value="g.id">{{ g.name }}</option>
							</optgroup>
						</select></label>
					<label class="field"><span>Only rows where</span>
						<select v-model="dl.form.filter_column" :class="{ invalid: dl.fieldErrors.filter_column }">
							<option value="">— every row —</option>
							<option v-for="c in columns" :key="c" :value="c">{{ c }}</option>
						</select>
						<span v-if="dl.fieldErrors.filter_column" class="warn small">{{ dl.fieldErrors.filter_column }}</span></label>
					<label v-if="dl.form.filter_column" class="field"><span>is one of (separate with commas)</span>
						<input v-model="dl.form.filter_text" placeholder="e.g. 100, 200" :class="{ invalid: dl.fieldErrors.filter_values }" />
						<span v-if="dl.fieldErrors.filter_values" class="warn small">{{ dl.fieldErrors.filter_values }}</span></label>
					<div class="field dl-columns"><span>Columns</span>
						<span class="row tight">
							<span class="dl-columns-summary" :class="{ invalid: dl.fieldErrors.columns }" :title="columnsSummary">{{ columnsSummary }}</span>
							<button type="button" class="secondary small" :disabled="!columns.length" @click="startColumns">Choose and order…</button>
						</span>
						<span v-if="dl.fieldErrors.columns" class="warn small">{{ dl.fieldErrors.columns }}</span></div>
				</div>

				<div class="dl-current" :class="{ problem: cur?.problem }">
					<template v-if="cur?.problem">
						<span><strong>Nothing to issue yet.</strong> {{ cur.problem }}</span>
						<span class="spacer" />
						<button v-if="isPanel" type="button" class="secondary" @click="openKeyList('distribution-panels')">Open Distribution Panels</button>
						<button v-else-if="isProject" type="button" class="secondary" @click="openKeyList('load-list')">Open the Load List</button>
						<button v-else type="button" class="secondary" @click="openGenerator">Open the generator</button>
					</template>
					<template v-else-if="isPanel && cur">
						<span>
							<strong>Current content:</strong> {{ cur.rows }} row(s), the schedule of {{ d.generator.replace('Distribution Panels: ', '') || 'its panel' }} as it is now.
							<template v-if="cur.changes">Since Rev {{ d.revisions[0]?.letter }}: {{ pending(cur.changes) }}.</template>
							<span v-for="w in cur.warnings" :key="w" class="warnText"> {{ w }}</span>
						</span>
						<span class="spacer" />
						<button type="button" class="secondary" @click="openKeyList('distribution-panels')">Open the panel</button>
						<button type="button" :disabled="dl.busy || dl.dirty" :title="dl.dirty ? 'Save the deliverable first' : ''" @click="startIssue">Issue Rev {{ cur.next_letter }}…</button>
					</template>
					<template v-else-if="isProject && cur">
						<span>
							<strong>Current content:</strong> {{ cur.rows }} row(s), from the {{ projectName(d.deliverable.type) }} as it is now{{ d.deliverable.filter_column ? ', filtered' : '' }}{{ d.deliverable.columns?.length ? `, ${d.deliverable.columns.length} column(s)` : '' }}.
							<template v-if="cur.changes">Since Rev {{ d.revisions[0]?.letter }}: {{ pending(cur.changes) }}.</template>
							<span v-for="w in cur.warnings" :key="w" class="warnText"> {{ w }}</span>
						</span>
						<span class="spacer" />
						<button v-if="MASTERS[d.deliverable.type]" type="button" class="secondary" @click="openMaster">Open the master list</button>
						<button v-else type="button" class="secondary" @click="openKeyList('load-list')">Load List</button>
						<button type="button" :disabled="dl.busy || dl.dirty" :title="dl.dirty ? 'Save the deliverable first' : ''" @click="startIssue">Issue Rev {{ cur.next_letter }}…</button>
					</template>
					<template v-else-if="cur?.build">
						<span>
							<strong>Current content:</strong> {{ cur.rows }} row(s) from build {{ cur.build.seq }} of {{ d.generator }}
							({{ when(cur.build.created_at) }}).
							<template v-if="cur.changes">Since Rev {{ d.revisions[0]?.letter }}: {{ pending(cur.changes) }}.</template>
							<span v-if="cur.stale" class="warnText"> The generator has changed since that build: build it again to include the changes.</span>
						</span>
						<span class="spacer" />
						<button type="button" class="secondary" @click="openGenerator">Open the generator</button>
						<button type="button" :disabled="dl.busy || dl.dirty" :title="dl.dirty ? 'Save the deliverable first' : ''" @click="startIssue">Issue Rev {{ cur.next_letter }}…</button>
					</template>
				</div>

				<div v-if="summary.length" class="row dl-summary">
					<span v-for="[label, value] in summary" :key="label" class="chip">{{ label }} <strong>{{ value }}</strong></span>
				</div>

				<div class="row dl-revs-head">
					<h3 class="dl-h">Revisions</h3>
					<span class="spacer" />
					<label v-if="d.revisions.length > 1" class="check small" title="The Excel file gets a second sheet, Changes: what changed against the revision before, or against the one chosen in Compared with">
						<input v-model="withChanges" type="checkbox"> Excel exports include a Changes sheet
					</label>
				</div>
				<table class="grid simple dl-revs">
					<thead><tr><th>Rev</th><th>Issued</th><th>By</th><th>Description</th><th>Rows</th><th>Since previous</th><th /></tr></thead>
					<tbody>
						<tr v-for="(r, i) in d.revisions" :key="r.id" :class="{ on: dl.shown?.info.id === r.id }">
							<td class="rev-letter">{{ r.letter }}</td>
							<td>{{ when(r.issued_at) }}</td>
							<td>{{ r.issued_by }}</td>
							<td class="desc">{{ r.description }} <button type="button" class="link small" title="Amend the description" @click="amend(r)">edit</button></td>
							<td class="num">{{ r.rows }}</td>
							<td>{{ r.added === null ? 'first issue' : `${r.added} added · ${r.removed} removed · ${r.changed} changed` }}</td>
							<td class="actions">
								<button type="button" class="secondary small" @click="dl.view(r); view = 'rows'">View</button>
								<button type="button" class="secondary small" @click="exportExcel(r)">Excel</button>
								<button type="button" class="secondary small" @click="dl.exportRevision(r, 'csv')">CSV</button>
								<button v-if="i === 0" type="button" class="secondary small" title="Withdraw this revision (only the latest can be)"
									@click="dl.error = null; withdrawing = { rev: r, reason: '' }">Withdraw</button>
							</td>
						</tr>
						<tr v-if="!d.revisions.length"><td colspan="7" class="hint">Not issued yet.</td></tr>
					</tbody>
				</table>

				<div class="row dl-view-head">
					<nav class="subtabs small inline">
						<button type="button" :class="{ active: !dl.shown }" @click="dl.view(null)">Current (not issued)</button>
						<button v-if="dl.shown" type="button" class="active">Rev {{ dl.shown.info.letter }}</button>
					</nav>
					<div class="seg">
						<button type="button" :class="view === 'rows' ? '' : 'secondary'" @click="view = 'rows'">Rows</button>
						<button type="button" :class="view === 'changes' ? '' : 'secondary'" :disabled="!content.changes" @click="view = 'changes'">
							Changes<span v-if="content.changes" class="count">{{ content.changes.added + content.changes.removed + content.changes.changed }}</span>
						</button>
					</div>
					<label v-if="dl.shown && others.length" class="small dl-against">Compared with
						<select v-model="against" :disabled="dl.busy" @change="pickAgainst">
							<option value="">the revision before</option>
							<option v-for="r in others" :key="r.id" :value="r.id">Rev {{ r.letter }}</option>
						</select>
					</label>
					<span class="hint small">{{ comparedText }}</span>
					<span class="spacer" />
					<button type="button" class="secondary small" :disabled="d.revisions.length > 0" :title="d.revisions.length ? 'A deliverable with revisions can\'t be deleted' : ''" @click="remove">Delete deliverable</button>
				</div>
				<div class="results mel-grid"><div ref="host" class="result-table" /></div>
			</section>

			<section v-else class="card wizard ref-empty">
				<h2>Deliverables</h2>
				<p class="hint">
					The lists this project issues: cable schedules, instrument lists, PLC I/O lists, equipment lists and load lists.
					Each takes its content from its Project Master list (which the Power and Instrument generators fill), through a filter and a choice and order of columns, and is issued in revisions A, B, C… when you say so. An issued
					revision is a frozen copy you can view, compare with the one before, and export at any time.
				</p>
				<button type="button" @click="startAdd()">New deliverable</button>
				<p v-if="dl.error && !adding" class="error">{{ dl.error }}</p>
			</section>
		</div>

		<AppModal :open="!!picking" title="Columns of this deliverable" @close="picking = null">
			<p class="hint small">Tick the columns to keep and put them in the order you want them. The column revisions are compared by has to stay.</p>
			<div class="row tight">
				<button type="button" class="secondary small" @click="setAllColumns(true)">Tick all</button>
				<button type="button" class="secondary small" @click="setAllColumns(false)">Untick all</button>
				<button type="button" class="secondary small" title="Every column, in the content's own order" @click="resetColumns">Back to all, in the list's order</button>
			</div>
			<ol v-if="picking" class="dl-column-list">
				<li v-for="(c, i) in picking" :key="c.name" :class="{ off: !c.on }">
					<label class="check"><input v-model="c.on" type="checkbox" /> {{ c.name }}</label>
					<span class="spacer" />
					<button type="button" class="secondary small" :disabled="i === 0" :title="`Move ${c.name} up`" @click="moveColumn(i, -1)">↑</button>
					<button type="button" class="secondary small" :disabled="i === picking.length - 1" :title="`Move ${c.name} down`" @click="moveColumn(i, 1)">↓</button>
				</li>
			</ol>
			<template #footer>
				<span v-if="picking" class="hint small">{{ picking.filter((c) => c.on).length }} of {{ picking.length }} kept</span>
				<span class="spacer" />
				<button type="button" class="secondary" @click="picking = null">Cancel</button>
				<button type="button" :disabled="!picking?.some((c) => c.on)" @click="applyColumns">OK</button>
			</template>
		</AppModal>

		<AppModal :open="!!adding" title="New deliverable" @close="adding = null">
			<form v-if="adding" class="form-grid" @submit.prevent="add">
				<label class="field"><span>Type</span>
					<select v-model="adding.type"><option v-for="t in types" :key="t" :value="t">{{ t }}</option></select></label>
				<label class="field"><span>Name<span class="req"> *</span></span>
					<input v-model="adding.name" placeholder="e.g. Lighting cable schedule" :class="{ invalid: dl.fieldErrors.name }" />
					<span v-if="dl.fieldErrors.name" class="warn small">{{ dl.fieldErrors.name }}</span></label>
				<label v-if="adding.type === PANEL_TYPE" class="field"><span>Distribution panel<span class="req"> *</span></span>
					<select v-model="adding.panel_id" :class="{ invalid: dl.fieldErrors.panel_id }">
						<option v-for="p in panels" :key="p.id" :value="p.id">{{ p.tag }}{{ p.title ? ` – ${p.title}` : '' }}</option>
					</select>
					<span v-if="!panels.length" class="warn small">There are no panels yet: add one in Project lists, Distribution Panels.</span>
					<span v-else-if="dl.fieldErrors.panel_id" class="warn small">{{ dl.fieldErrors.panel_id }}</span></label>
				<label v-else class="field"><span>Content from<span class="req"> *</span></span>
					<select v-model="adding.generator_id" :class="{ invalid: dl.fieldErrors.generator_id }">
						<option :value="PROJECT">{{ projectName(adding.type) }}</option>
						<optgroup v-if="generators.length" label="Generators from imported workbooks">
							<option v-for="g in generators" :key="g.id" :value="g.id">{{ g.name }}</option>
						</optgroup>
					</select>
					<span v-if="dl.fieldErrors.generator_id" class="warn small">{{ dl.fieldErrors.generator_id }}</span></label>
				<p v-if="adding.type === PANEL_TYPE" class="hint small">The panel's schedule as it is when you issue it: one row for each pole of each way, with the panel's ratings and totals.</p>
				<p v-else-if="adding.generator_id === PROJECT && MASTERS[adding.type]" class="hint small">The {{ projectName(adding.type) }} holds every row the Power and Instrument generators make. After creating the deliverable you can keep only some rows (a filter) and choose and order its columns. It is always up to date until you issue a revision, which freezes it.</p>
				<p v-else-if="adding.generator_id === PROJECT" class="hint small">Every load in the Load List adds the rows its load type has for this type of list. Nothing to build: it is always up to date.</p>
				<button type="submit" hidden />
			</form>
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="adding = null">Cancel</button>
				<button type="button" :disabled="dl.busy || !adding?.name.trim() || (adding.type === PANEL_TYPE ? !adding.panel_id : !adding.generator_id)" @click="add">Create</button>
			</template>
		</AppModal>

		<AppModal :open="!!issuing" :title="`Issue Rev ${cur?.next_letter ?? ''}`" @close="issuing = null">
			<template v-if="issuing && d && cur">
				<p>
					This freezes <strong>{{ d.deliverable.name }}</strong> as <strong>Rev {{ cur.next_letter }}</strong>.
					<template v-if="!issuing.build_id">It will hold {{ cur.rows }} row(s)<template v-if="cur.changes">: {{ pending(cur.changes) }} since Rev {{ d.revisions[0]?.letter }}</template>.</template>
				</p>
				<p v-if="nothingNew && !issuing.build_id" class="warn">Nothing has changed since Rev {{ d.revisions[0]?.letter }}.</p>
				<p v-if="cur.stale && !issuing.build_id" class="warn">The generator has changed since its latest build. Those changes are not in this revision.</p>
				<label class="field"><span>Description</span>
					<input v-model="issuing.description" placeholder="e.g. Issued for review" /></label>
				<label v-if="!isProject" class="field"><span>From build</span>
					<select v-model="issuing.build_id">
						<option value="">Latest (build {{ cur.build?.seq }})</option>
						<option v-for="b in d.builds.slice(1)" :key="b.id" :value="b.id">Build {{ b.seq }}, {{ when(b.created_at) }}</option>
					</select></label>
				<p v-if="dl.error" class="error">{{ dl.error }}</p>
			</template>
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="issuing = null">Cancel</button>
				<button type="button" :disabled="dl.busy" @click="issue">Issue Rev {{ cur?.next_letter }}</button>
			</template>
		</AppModal>

		<AppModal :open="!!withdrawing" :title="`Withdraw Rev ${withdrawing?.rev.letter ?? ''}`" @close="withdrawing = null">
			<template v-if="withdrawing">
				<p>
					Withdrawing deletes the frozen copy of <strong>Rev {{ withdrawing.rev.letter }}</strong>. The next issue will be
					Rev {{ withdrawing.rev.letter }} again. The change log keeps a record of the withdrawal.
				</p>
				<label class="field"><span>Reason<span class="req"> *</span></span>
					<input v-model="withdrawing.reason" placeholder="Why is it withdrawn?" :class="{ invalid: dl.fieldErrors.reason }" /></label>
				<p v-if="dl.error" class="error">{{ dl.error }}</p>
			</template>
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="withdrawing = null">Cancel</button>
				<button type="button" :disabled="dl.busy || !withdrawing?.reason.trim()" @click="withdraw">Withdraw Rev {{ withdrawing?.rev.letter }}</button>
			</template>
		</AppModal>
	</div>
</template>
