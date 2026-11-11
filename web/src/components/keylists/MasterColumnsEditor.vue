<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The project's columns of the Project Master lists: rename, add, reorder and delete them.
// A rename follows in the load types' and equipment types' rows and in the deliverables made
// from the list; a delete drops those cells and takes the column out of those deliverables.
// Issued revisions keep the columns they were issued with. Saving first asks the engine what
// the change would do, and shows it to confirm.
import { computed, ref, watch } from 'vue';
import { ApiError, apiGet, apiPut } from '../../lib/engine';
import AppModal from '../common/AppModal.vue';
import HistoryButton from '../audit/HistoryButton.vue';

type ListColumns = { key: string; name: string; columns: string[]; protected: string[]; defaults: string[] };
type ColumnsView = { lists: ListColumns[]; extra: string[]; reserved: string[] };
type Impact = { key: string; name: string; renames: Record<string, string>; deletes: string[]; added: string[]; cells_dropped: number; deliverables: string[] };
type Saved = { view: ColumnsView; impact: Impact[]; saved: boolean };
type Col = { uid: number; name: string; was: string };

const props = defineProps<{ open: boolean; listKey: string }>();
const emit = defineEmits<{ close: []; saved: [] }>();
const API = '/api/master-columns';

const view = ref<ColumnsView | null>(null);
const key = ref(props.listKey);
const drafts = ref<Record<string, Col[]>>({});
const error = ref('');
const fields = ref<Record<string, string>>({});
const busy = ref(false);
const confirm = ref<Impact[] | null>(null);
let uid = 0;

const list = computed(() => view.value?.lists.find((l) => l.key === key.value));
const cols = computed(() => drafts.value[key.value] ?? []);
const norm = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
const isProtected = (c: Col) => !!c.was && !!list.value?.protected.includes(c.was);

function reset(v: ColumnsView) {
	view.value = v;
	drafts.value = Object.fromEntries(v.lists.map((l) => [l.key, l.columns.map((name) => ({ uid: ++uid, name, was: name }))]));
}

async function load() {
	error.value = '';
	fields.value = {};
	confirm.value = null;
	key.value = props.listKey;
	try {
		reset(await apiGet<ColumnsView>(API));
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	}
}
watch(() => props.open, (open) => { if (open) void load(); }, { immediate: true });
watch(drafts, () => { confirm.value = null; }, { deep: true }); // a change after Save… needs checking again

const changed = (l: ListColumns) => {
	const d = drafts.value[l.key] ?? [];
	return d.length !== l.columns.length || d.some((c, i) => c.name.trim() !== l.columns[i] || c.was !== l.columns[i]);
};
const dirtyLists = computed(() => view.value?.lists.filter(changed) ?? []);

// Same rules as the engine, so problems show while typing.
const problems = computed(() => {
	const out: Record<number, string> = {};
	const reserved = new Set((view.value?.reserved ?? []).map(norm));
	const seen = new Set<string>();
	for (const c of cols.value) {
		const n = norm(c.name);
		if (!n) out[c.uid] = 'A column needs a name';
		else if (reserved.has(n)) out[c.uid] = `'${c.name.trim()}' is kept for the master list's own use`;
		else if (seen.has(n)) out[c.uid] = `'${c.name.trim()}' is in the list twice`;
		else if (isProtected(c) && c.name.trim() !== c.was) out[c.uid] = `'${c.was}' can be moved but not renamed`;
		seen.add(n);
	}
	cols.value.forEach((c, i) => { const f = fields.value[`${key.value}.${i}`]; if (f && !out[c.uid]) out[c.uid] = f; });
	return out;
});
const anyProblems = computed(() => {
	const reserved = new Set((view.value?.reserved ?? []).map(norm));
	return Object.values(drafts.value).some((d) => {
		const seen = new Set<string>();
		return d.some((c) => {
			const n = norm(c.name);
			const bad = !n || reserved.has(n) || seen.has(n);
			seen.add(n);
			return bad;
		});
	});
});

function move(i: number, by: -1 | 1) {
	const d = cols.value;
	if (i + by >= 0 && i + by < d.length) [d[i], d[i + by]] = [d[i + by], d[i]];
}
function add() {
	cols.value.push({ uid: ++uid, name: '', was: '' });
}
function remove(i: number) {
	cols.value.splice(i, 1);
}
function restoreDefaults() {
	const l = list.value;
	if (!l) return;
	const now = new Map(cols.value.filter((c) => c.was).map((c) => [norm(c.was), c.was]));
	drafts.value[l.key] = l.defaults.map((name) => ({ uid: ++uid, name, was: now.get(norm(name)) ?? '' }));
}

function body() {
	return { lists: Object.fromEntries(dirtyLists.value.map((l) => [l.key, drafts.value[l.key].map((c) => ({ name: c.name, was: c.was }))])) };
}

async function put(dryRun: boolean): Promise<Saved | null> {
	busy.value = true;
	error.value = '';
	fields.value = {};
	try {
		return await apiPut<Saved>(`${API}?dry_run=${dryRun}`, body());
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
		if (err instanceof ApiError) {
			fields.value = err.fields;
			const bad = Object.keys(err.fields).map((f) => f.split('.')[0]).find((k) => drafts.value[k]);
			if (bad) key.value = bad;
		}
		return null;
	} finally {
		busy.value = false;
	}
}

async function check() {
	const r = await put(true);
	if (r) confirm.value = r.impact;
}

async function save() {
	const r = await put(false);
	if (!r) { confirm.value = null; return; }
	reset(r.view);
	confirm.value = null;
	emit('saved');
	emit('close');
}

const renameText = (i: Impact) => Object.entries(i.renames).map(([a, b]) => `${a} → ${b}`).join(', ');
</script>

<template>
	<AppModal :open="open" title="Columns of the Project Master lists" @close="emit('close')">
		<div class="mcol">
			<p class="hint small">
				Rename, add, delete and reorder each master list's columns for this project. Load type and equipment type rows, the
				Excel import and export, and the deliverables made from the list follow. Issued revisions keep the columns they were
				issued with. Columns with 🔒 can be moved but not renamed or deleted: revisions are compared by them, or
				"Per power cable" rows fill them in.
			</p>
			<p v-if="error" class="error">{{ error }}</p>
			<div v-if="view" class="sym-tabs" role="tablist">
				<button v-for="l in view.lists" :key="l.key" type="button" role="tab" :aria-selected="key === l.key"
					:class="{ on: key === l.key }" @click="key = l.key; confirm = null">
					{{ l.name.replace('Project Master ', '') }}<span v-if="changed(l)" class="unsaved"> ●</span>
				</button>
			</div>
			<ol v-if="list" class="dl-column-list mcol-list">
				<li v-for="(c, i) in cols" :key="c.uid" :class="{ invalid: problems[c.uid] }">
					<span class="mcol-lock" :title="isProtected(c) ? 'Can be moved, not renamed or deleted' : ''">{{ isProtected(c) ? '🔒' : '' }}</span>
					<input v-model="c.name" :aria-label="`Column ${i + 1} name`" :readonly="isProtected(c)" :class="{ invalid: problems[c.uid] }"
						:placeholder="c.was ? '' : 'New column name'" :title="problems[c.uid] ?? ''" />
					<span v-if="c.was && c.name.trim() !== c.was" class="hint small">was {{ c.was }}</span>
					<span v-else-if="!c.was" class="chip small">new</span>
					<span v-if="problems[c.uid]" class="warn small">{{ problems[c.uid] }}</span>
					<span class="spacer" />
					<button type="button" class="secondary small" :disabled="i === 0" :title="`Move ${c.name} up`" @click="move(i, -1)">↑</button>
					<button type="button" class="secondary small" :disabled="i === cols.length - 1" :title="`Move ${c.name} down`" @click="move(i, 1)">↓</button>
					<button type="button" class="secondary small" :disabled="isProtected(c)"
						:title="isProtected(c) ? 'This column can\'t be deleted' : `Delete ${c.name}`" @click="remove(i)">✕</button>
				</li>
				<li v-for="x in view?.extra ?? []" :key="x" class="off" title="Added by the master list after its own columns">
					<span class="mcol-lock" /> {{ x }} <span class="hint small">always last</span>
				</li>
			</ol>
			<div class="row tight">
				<button type="button" class="secondary small" @click="add">+ Add column</button>
				<button type="button" class="secondary small" title="The built-in columns, in their order (renamed ones go back to their built-in name)"
					@click="restoreDefaults">Back to the built-in columns</button>
				<span class="spacer" />
				<HistoryButton entity="master_columns" record-id="master-columns" label="Master list columns" />
			</div>
			<div v-if="confirm" class="mcol-confirm">
				<strong>Saving will:</strong>
				<p v-if="!confirm.length" class="hint small">Change nothing.</p>
				<ul>
					<li v-for="i in confirm" :key="i.key">
						<strong>{{ i.name.replace('Project Master ', '') }}</strong>:
						<span v-if="Object.keys(i.renames).length"> rename {{ renameText(i) }};</span>
						<span v-if="i.added.length"> add {{ i.added.join(', ') }};</span>
						<span v-if="i.deletes.length" class="warnText"> delete {{ i.deletes.join(', ') }}<template v-if="i.cells_dropped">, dropping
							{{ i.cells_dropped }} filled-in cell(s) from load type and equipment type rows</template>;</span>
						<span v-if="!Object.keys(i.renames).length && !i.added.length && !i.deletes.length"> reorder the columns;</span>
						<span v-if="i.deliverables.length"> update the deliverable(s) {{ i.deliverables.join(', ') }}.</span>
					</li>
				</ul>
			</div>
		</div>
		<template #footer>
			<span v-if="dirtyLists.length" class="unsaved">● {{ dirtyLists.length }} list(s) changed</span>
			<span class="spacer" />
			<button type="button" class="secondary" @click="emit('close')">Cancel</button>
			<button v-if="!confirm" type="button" :disabled="busy || !dirtyLists.length || anyProblems" @click="check">Save…</button>
			<template v-else>
				<button type="button" class="secondary" @click="confirm = null">Back</button>
				<button type="button" :disabled="busy" @click="save">Confirm and save</button>
			</template>
		</template>
	</AppModal>
</template>
