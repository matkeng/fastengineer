<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import type { Changes, RevisionInfo } from '../../lib/deliverableTypes';
import { type BuildResult, type OutputRow, type Scalar, cellText } from '../../lib/genTypes';
import { useDeliverables } from '../../stores/deliverables';
import { useGenerators } from '../../stores/generators';
import { useUi } from '../../stores/ui';
import HistoryButton from '../audit/HistoryButton.vue';
import AppModal from '../common/AppModal.vue';

// Deliverables: the lists a project issues. Each takes its content from a generator's builds
// and is issued in lettered revisions (A, B, ...), frozen when the user issues them.
const dl = useDeliverables();
const gens = useGenerators();
const ui = useUi();

const types = computed(() => dl.overview?.types ?? []);
const generators = computed(() => dl.overview?.generators ?? []);
const groups = computed(() => types.value.map((t) => ({ type: t, items: (dl.overview?.deliverables ?? []).filter((s) => s.deliverable.type === t) })));
const d = computed(() => dl.detail);
const cur = computed(() => d.value?.current ?? null);
const columns = computed(() => generators.value.find((g) => g.id === dl.form?.generator_id)?.columns ?? []);
const when = (iso: string) => new Date(iso).toLocaleString();

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
const adding = ref<{ type: string; name: string; generator_id: string } | null>(null);
function startAdd(type?: string) {
	dl.error = null;
	adding.value = { type: type ?? types.value[0] ?? '', name: '', generator_id: generators.value[0]?.id ?? '' };
}
async function add() {
	const a = adding.value;
	if (!a) return;
	if (dl.dirty && !confirm('Discard unsaved changes to the open deliverable?')) return;
	if (await dl.create(a.type, a.name, a.generator_id)) adding.value = null;
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
		return { result: dl.shown.result, changes: dl.shown.changes, key: dl.shown.diff_key, title: `Rev ${dl.shown.info.letter}` };
	}
	return { result: cur.value?.result ?? null, changes: cur.value?.changes ?? null, key: '', title: 'Current (not issued)' };
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
						<select v-model="dl.form.type"><option v-for="t in types" :key="t" :value="t">{{ t }}</option></select></label>
					<label class="field"><span>Document number</span><input v-model="dl.form.doc_number" class="mono" /></label>
					<label class="field"><span>Document title</span><input v-model="dl.form.doc_title" /></label>
					<label class="field"><span>Generator<span class="req"> *</span></span>
						<select v-model="dl.form.generator_id" :class="{ invalid: dl.fieldErrors.generator_id }">
							<option v-for="g in generators" :key="g.id" :value="g.id">{{ g.name }}</option>
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
				</div>

				<div class="dl-current" :class="{ problem: cur?.problem }">
					<template v-if="cur?.problem">
						<strong>Nothing to issue yet.</strong> {{ cur.problem }}
						<span class="spacer" />
						<button type="button" class="secondary" @click="openGenerator">Open the generator</button>
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

				<h3 class="dl-h">Revisions</h3>
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
								<button type="button" class="secondary small" @click="dl.exportRevision(r, 'xlsx')">Excel</button>
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
					<span class="hint small">{{ dl.shown ? `As issued on ${when(dl.shown.info.issued_at)}; changes are against the revision before it.` : 'What a new revision would contain; changes are against the latest revision.' }}</span>
					<span class="spacer" />
					<button type="button" class="secondary small" :disabled="d.revisions.length > 0" :title="d.revisions.length ? 'A deliverable with revisions can\'t be deleted' : ''" @click="remove">Delete deliverable</button>
				</div>
				<div class="results mel-grid"><div ref="host" class="result-table" /></div>
			</section>

			<section v-else class="card wizard ref-empty">
				<h2>Deliverables</h2>
				<p class="hint">
					The lists this project issues: cable schedules, instrument lists, PLC I/O lists, equipment lists and load lists.
					Each takes its content from a generator's builds and is issued in revisions A, B, C… when you say so. An issued
					revision is a frozen copy you can view, compare with the one before, and export at any time.
				</p>
				<p v-if="!generators.length" class="warn">There are no generators in this project yet. Import one in Generators first.</p>
				<button v-else type="button" @click="startAdd()">New deliverable</button>
				<p v-if="dl.error && !adding" class="error">{{ dl.error }}</p>
			</section>
		</div>

		<AppModal :open="!!adding" title="New deliverable" @close="adding = null">
			<form v-if="adding" class="form-grid" @submit.prevent="add">
				<label class="field"><span>Type</span>
					<select v-model="adding.type"><option v-for="t in types" :key="t" :value="t">{{ t }}</option></select></label>
				<label class="field"><span>Name<span class="req"> *</span></span>
					<input v-model="adding.name" placeholder="e.g. Lighting cable schedule" :class="{ invalid: dl.fieldErrors.name }" />
					<span v-if="dl.fieldErrors.name" class="warn small">{{ dl.fieldErrors.name }}</span></label>
				<label class="field"><span>Generator<span class="req"> *</span></span>
					<select v-model="adding.generator_id" :class="{ invalid: dl.fieldErrors.generator_id }">
						<option v-for="g in generators" :key="g.id" :value="g.id">{{ g.name }}</option>
					</select>
					<span v-if="dl.fieldErrors.generator_id" class="warn small">{{ dl.fieldErrors.generator_id }}</span></label>
				<p v-if="!generators.length" class="warn">Import a generator in Generators first.</p>
				<button type="submit" hidden />
			</form>
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="adding = null">Cancel</button>
				<button type="button" :disabled="dl.busy || !adding?.name.trim() || !adding.generator_id" @click="add">Create</button>
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
				<label class="field"><span>From build</span>
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
