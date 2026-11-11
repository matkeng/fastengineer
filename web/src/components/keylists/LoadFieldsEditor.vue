<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The project's fields of the Project Master Load List: what List import maps its columns onto
// and what the Load List shows. Rename, add, delete and reorder them. A field keeps its key
// (shown as the <<tag>> load types' rows use) when renamed, so mappings and tags keep working;
// a deleted field is taken out of every import's mapping. Fields the app reads have 🔒: they
// can be renamed and moved, not deleted. Saving first shows what the change would do.
import { computed, ref, watch } from 'vue';
import { ApiError, apiGet, apiPut } from '../../lib/engine';
import AppModal from '../common/AppModal.vue';
import HistoryButton from '../audit/HistoryButton.vue';

type Kind = 'text' | 'number' | 'yes/no';
type FieldView = { key: string; label: string; kind: Kind; locked: boolean };
type View = { fields: FieldView[]; kinds: Kind[] };
type Deleted = { key: string; label: string; imports: string[]; rows: number; template_rows: number };
type Impact = { relabelled: Record<string, [string, string]>; added: string[]; deleted: Deleted[]; rekinded: Record<string, [string, string]>; reordered: boolean };
type Saved = { view: View; impact: Impact; saved: boolean };
type Row = { uid: number; key: string; label: string; kind: Kind; locked: boolean; was: string };

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; saved: [] }>();
const API = '/api/load-fields';
const KINDS: Kind[] = ['text', 'number', 'yes/no'];

const view = ref<View | null>(null);
const rows = ref<Row[]>([]);
const error = ref('');
const fields = ref<Record<string, string>>({});
const busy = ref(false);
const confirm = ref<Impact | null>(null);
let uid = 0;

function reset(v: View) {
	view.value = v;
	rows.value = v.fields.map((f) => ({ uid: ++uid, key: f.key, label: f.label, kind: f.kind, locked: f.locked, was: f.label }));
}

async function load() {
	error.value = '';
	fields.value = {};
	confirm.value = null;
	try {
		reset(await apiGet<View>(API));
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	}
}
watch(() => props.open, (o) => { if (o) void load(); }, { immediate: true });
watch(rows, () => { confirm.value = null; }, { deep: true });

const dirty = computed(() => {
	const v = view.value?.fields ?? [];
	return rows.value.length !== v.length || rows.value.some((r, i) => r.key !== v[i].key || r.label.trim() !== v[i].label || r.kind !== v[i].kind);
});

// Same rules as the engine, so problems show while typing.
const problems = computed(() => {
	const out: Record<number, string> = {};
	const seen = new Set<string>();
	rows.value.forEach((r, i) => {
		const n = r.label.trim().replace(/\s+/g, ' ').toLowerCase();
		if (!n) out[r.uid] = 'A field needs a name';
		else if (seen.has(n)) out[r.uid] = `'${r.label.trim()}' is in the list twice`;
		seen.add(n);
		const f = fields.value[String(i)];
		if (f && !out[r.uid]) out[r.uid] = f;
	});
	return out;
});
const problemCount = computed(() => Object.keys(problems.value).length);

function move(i: number, by: -1 | 1) {
	const d = rows.value;
	if (i + by >= 0 && i + by < d.length) [d[i], d[i + by]] = [d[i + by], d[i]];
}
function add() {
	rows.value.push({ uid: ++uid, key: '', label: '', kind: 'text', locked: false, was: '' });
}

async function put(dryRun: boolean): Promise<Saved | null> {
	busy.value = true;
	error.value = '';
	fields.value = {};
	try {
		return await apiPut<Saved>(`${API}?dry_run=${dryRun}`, { fields: rows.value.map((r) => ({ key: r.key, label: r.label, kind: r.kind })) });
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
		if (err instanceof ApiError) fields.value = err.fields;
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
const nothing = (i: Impact) => !Object.keys(i.relabelled).length && !i.added.length && !i.deleted.length && !Object.keys(i.rekinded).length && !i.reordered;
</script>

<template>
	<AppModal :open="open" title="Fields of the Project Master Load List" @close="emit('close')">
		<div class="mcol">
			<p class="hint small">
				What List import maps a file's columns onto, and what the Load List shows. Rename, add, delete and reorder them for this
				project. A field keeps its <code>&lt;&lt;tag&gt;&gt;</code> (used in load types' rows) when it is renamed, so mappings and
				tags keep working. A deleted field is taken out of every import's mapping. Fields with 🔒 are read by the app (allocations,
				deliverables, distribution panels): they can be renamed and moved, not deleted.
			</p>
			<p v-if="error" class="error">{{ error }}</p>
			<ol class="dl-column-list mcol-list">
				<li v-for="(r, i) in rows" :key="r.uid" :class="{ invalid: problems[r.uid] }">
					<span class="mcol-lock" :title="r.locked ? 'Read by the app: it can be renamed and moved, not deleted' : ''">{{ r.locked ? '🔒' : '' }}</span>
					<input v-model="r.label" :aria-label="`Field ${i + 1} name`" :class="{ invalid: problems[r.uid] }" :placeholder="r.key ? '' : 'New field name'"
						:title="problems[r.uid] ?? ''" />
					<select v-model="r.kind" :disabled="r.locked" :aria-label="`Field ${i + 1} kind`" title="How the import reads it: numbers are read as numbers, yes/no as true or false">
						<option v-for="k in KINDS" :key="k" :value="k">{{ k }}</option>
					</select>
					<code v-if="r.key" class="hint small" title="Its tag in load types' rows">&lt;&lt;{{ r.key }}&gt;&gt;</code>
					<span v-else class="chip small">new</span>
					<span v-if="r.key && r.label.trim() !== r.was" class="hint small">was {{ r.was }}</span>
					<span v-if="problems[r.uid]" class="warn small">{{ problems[r.uid] }}</span>
					<span class="spacer" />
					<button type="button" class="secondary small" :disabled="i === 0" :title="`Move ${r.label} up`" @click="move(i, -1)">↑</button>
					<button type="button" class="secondary small" :disabled="i === rows.length - 1" :title="`Move ${r.label} down`" @click="move(i, 1)">↓</button>
					<button type="button" class="secondary small" :disabled="r.locked" :title="r.locked ? 'This field can\'t be deleted' : `Delete ${r.label}`"
						@click="rows.splice(i, 1)">✕</button>
				</li>
			</ol>
			<div class="row tight">
				<button type="button" class="secondary small" @click="add">+ Add field</button>
				<span class="spacer" />
				<HistoryButton entity="load_fields" record-id="load-fields" label="Load List fields" />
			</div>
			<div v-if="confirm" class="mcol-confirm">
				<strong>Saving will:</strong>
				<ul>
					<li v-if="nothing(confirm)" class="hint">change nothing.</li>
					<li v-for="(v, k) in confirm.relabelled" :key="`r${k}`">rename {{ v[0] }} → {{ v[1] }} (its tag stays &lt;&lt;{{ k }}&gt;&gt;)</li>
					<li v-if="confirm.added.length">add {{ confirm.added.join(', ') }}</li>
					<li v-for="(v, k) in confirm.rekinded" :key="`k${k}`">read {{ k }} as {{ v[1] }} instead of {{ v[0] }}</li>
					<li v-for="d in confirm.deleted" :key="d.key" class="warnText">
						delete {{ d.label }}<template v-if="d.imports.length">: it is taken out of the mapping of {{ d.imports.join(', ') }}</template><template
							v-if="d.rows">; {{ d.rows }} Load List row(s) have a value in it</template><template
							v-if="d.template_rows">; {{ d.template_rows }} load type / equipment type row(s) use &lt;&lt;{{ d.key }}&gt;&gt; and will show it blank</template>
					</li>
					<li v-if="confirm.reordered">put the fields in the new order</li>
				</ul>
			</div>
		</div>
		<template #footer>
			<span v-if="problemCount" class="warn small">{{ problemCount }} problem(s)</span>
			<span v-else-if="dirty" class="unsaved">● Unsaved changes</span>
			<span class="spacer" />
			<button type="button" class="secondary" @click="emit('close')">Cancel</button>
			<button v-if="!confirm" type="button" :disabled="busy || !dirty || problemCount > 0" @click="check">Save…</button>
			<template v-else>
				<button type="button" class="secondary" @click="confirm = null">Back</button>
				<button type="button" :disabled="busy" @click="save">Confirm and save</button>
			</template>
		</template>
	</AppModal>
</template>
