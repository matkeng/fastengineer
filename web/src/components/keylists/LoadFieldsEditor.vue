<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The project's fields of the Project Master Load List: what List import maps its columns onto
// and what the Load List shows. Rename, add, delete and reorder them. A field keeps its key
// (shown as the <<tag>> load types' rows use) when renamed, so mappings and tags keep working;
// a deleted field is taken out of every import's mapping. Fields the app reads have 🔒: they
// can be renamed and moved, not deleted. Saving first shows what the change would do.
// A calculated field is worked out for each row like a spreadsheet formula: Applies when (which
// rows it is for), one formula referring to the row's cells as <<field>>, and checks on the answer.
import { computed, ref, watch } from 'vue';
import { ApiError, apiGet, apiPostJson, apiPut } from '../../lib/engine';
import AppModal from '../common/AppModal.vue';
import HistoryButton from '../audit/HistoryButton.vue';

type Kind = 'text' | 'number' | 'yes/no' | 'calc';
type Check = { rule: string; message: string; severity: 'error' | 'warning' };
type Calc = { applies_if: string; formula: string; otherwise: string; decimals: number | null; checks: Check[] };
type FieldView = { key: string; label: string; kind: Kind; locked: boolean; calc: Calc | null };
type View = { fields: FieldView[]; kinds: Kind[]; app_refs: { ref: string; label: string }[]; functions: string[]; text_functions: string[] };
type Issue = { field: string; severity: string; message: string };
type Preview = { rows: { tag: string; value: string | number | boolean | null; issues: Issue[] }[]; total: number; errors: number; warnings: number };
type Deleted = { key: string; label: string; imports: string[]; rows: number; template_rows: number };
type Impact = { relabelled: Record<string, [string, string]>; added: string[]; deleted: Deleted[]; rekinded: Record<string, [string, string]>; recalculated: string[]; reordered: boolean };
type Saved = { view: View; impact: Impact; saved: boolean };
type Row = { uid: number; key: string; label: string; kind: Kind; locked: boolean; was: string; calc: Calc };

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; saved: [] }>();
const API = '/api/load-fields';
const KINDS: Kind[] = ['text', 'number', 'yes/no', 'calc'];
const KIND_NAMES: Record<Kind, string> = { text: 'text', number: 'number', 'yes/no': 'yes/no', calc: 'calculated' };
const blankCalc = (): Calc => ({ applies_if: '', formula: '', otherwise: '', decimals: null, checks: [] });
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

const view = ref<View | null>(null);
const rows = ref<Row[]>([]);
const error = ref('');
const fields = ref<Record<string, string>>({});
const busy = ref(false);
const confirm = ref<Impact | null>(null);
let uid = 0;
const openCalc = ref<number | null>(null); // the uid of the calculated field being edited
const preview = ref<Preview | null>(null);
const previewing = ref(false);
let focused: { el: HTMLInputElement | HTMLTextAreaElement; set: (v: string) => void } | null = null;

function reset(v: View) {
	view.value = v;
	rows.value = v.fields.map((f) => ({ uid: ++uid, key: f.key, label: f.label, kind: f.kind, locked: f.locked, was: f.label, calc: f.calc ? clone(f.calc) : blankCalc() }));
	openCalc.value = null;
	preview.value = null;
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
watch(openCalc, () => { preview.value = null; });

const dirty = computed(() => {
	const v = view.value?.fields ?? [];
	return rows.value.length !== v.length || rows.value.some((r, i) => r.key !== v[i].key || r.label.trim() !== v[i].label || r.kind !== v[i].kind
		|| (r.kind === 'calc' && JSON.stringify(r.calc) !== JSON.stringify(v[i].calc ?? blankCalc())));
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
		if (r.kind === 'calc' && !r.calc.formula.trim()) out[r.uid] = 'A calculated field needs a formula';
		const f = fields.value[String(i)] ?? Object.entries(fields.value).find(([k]) => k.startsWith(`${i}.`))?.[1];
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
	rows.value.push({ uid: ++uid, key: '', label: '', kind: 'text', locked: false, was: '', calc: blankCalc() });
}
function addCalc() {
	const r: Row = { uid: ++uid, key: '', label: '', kind: 'calc', locked: false, was: '', calc: blankCalc() };
	rows.value.push(r);
	openCalc.value = r.uid;
}
const body = () => ({ fields: rows.value.map((r) => ({ key: r.key, label: r.label, kind: r.kind, calc: r.kind === 'calc' ? r.calc : null })) });
const fieldError = (i: number, part: string) => fields.value[`${i}.${part}`] ?? '';

/** Where "Insert" puts a reference: the box last typed in. */
function track(e: FocusEvent, set: (v: string) => void) {
	focused = { el: e.target as HTMLInputElement | HTMLTextAreaElement, set };
}
function insert(ref: string) {
	if (!ref || !focused) return;
	const { el, set } = focused;
	const at = el.selectionStart ?? el.value.length;
	const end = el.selectionEnd ?? at;
	set(el.value.slice(0, at) + ref + el.value.slice(end));
	requestAnimationFrame(() => { el.focus(); el.setSelectionRange(at + ref.length, at + ref.length); });
}
/** What a formula can refer to: every field (by its tag) but itself, then what the app works out. */
const references = (r: Row) => [
	...rows.value.filter((x) => x.key && x.uid !== r.uid).map((x) => ({ ref: `<<${x.key}>>`, label: x.label + (x.kind === 'calc' ? ' (calculated)' : '') })),
	...(view.value?.app_refs ?? []),
];

async function runPreview(i: number) {
	previewing.value = true;
	error.value = '';
	fields.value = {};
	try {
		preview.value = await apiPostJson<Preview>(`${API}/preview`, { ...body(), field: i });
	} catch (err) {
		preview.value = null;
		error.value = err instanceof Error ? err.message : String(err);
		if (err instanceof ApiError) fields.value = err.fields;
	} finally {
		previewing.value = false;
	}
}
const shown = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : typeof v === 'boolean' ? (v ? 'TRUE' : 'FALSE') : String(v));

async function put(dryRun: boolean): Promise<Saved | null> {
	busy.value = true;
	error.value = '';
	fields.value = {};
	try {
		return await apiPut<Saved>(`${API}?dry_run=${dryRun}`, body());
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
const nothing = (i: Impact) => !Object.keys(i.relabelled).length && !i.added.length && !i.deleted.length && !Object.keys(i.rekinded).length
	&& !i.recalculated.length && !i.reordered;
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
					<select v-model="r.kind" :disabled="r.locked" :aria-label="`Field ${i + 1} kind`"
						title="How the import reads it (numbers as numbers, yes/no as true or false), or calculated: worked out for each row from a formula">
						<option v-for="k in KINDS" :key="k" :value="k">{{ KIND_NAMES[k] }}</option>
					</select>
					<code v-if="r.key" class="hint small" title="Its tag in load types' rows">&lt;&lt;{{ r.key }}&gt;&gt;</code>
					<span v-else class="chip small">new</span>
					<span v-if="r.key && r.label.trim() !== r.was" class="hint small">was {{ r.was }}</span>
					<span v-if="problems[r.uid]" class="warn small">{{ problems[r.uid] }}</span>
					<span class="spacer" />
					<button v-if="r.kind === 'calc'" type="button" class="secondary small" :class="{ on: openCalc === r.uid }"
						:title="`The formula, when it applies and its checks`" @click="openCalc = openCalc === r.uid ? null : r.uid">ƒ Formula…</button>
					<button type="button" class="secondary small" :disabled="i === 0" :title="`Move ${r.label} up`" @click="move(i, -1)">↑</button>
					<button type="button" class="secondary small" :disabled="i === rows.length - 1" :title="`Move ${r.label} down`" @click="move(i, 1)">↓</button>
					<button type="button" class="secondary small" :disabled="r.locked" :title="r.locked ? 'This field can\'t be deleted' : `Delete ${r.label}`"
						@click="rows.splice(i, 1)">✕</button>
					<div v-if="r.kind === 'calc' && openCalc === r.uid" class="lf-calc">
						<label class="lf-part"><span>Applies when <span class="hint small">which rows it is for; blank: every row</span></span>
							<input :value="r.calc.applies_if" placeholder="e.g. <<load_rating>> != '' and <<loadtype>> != 'SPARE'" :class="{ invalid: fieldError(i, 'applies_if') }"
								@input="r.calc.applies_if = ($event.target as HTMLInputElement).value" @focus="track($event, (v) => (r.calc.applies_if = v))" /></label>
						<span v-if="fieldError(i, 'applies_if')" class="warn small">{{ fieldError(i, 'applies_if') }}</span>
						<label class="lf-part"><span>Formula <span class="hint small">one expression; the row's cells are &lt;&lt;field&gt;&gt;</span></span>
							<textarea :value="r.calc.formula" rows="2" class="mono" placeholder="e.g. <<load_rating>> * 0.746 if <<units>> == 'HP' else <<load_rating>>"
								:class="{ invalid: fieldError(i, 'formula') }" @input="r.calc.formula = ($event.target as HTMLTextAreaElement).value"
								@focus="track($event, (v) => (r.calc.formula = v))" /></label>
						<span v-if="fieldError(i, 'formula')" class="warn small">{{ fieldError(i, 'formula') }}</span>
						<div class="lf-pair">
							<label class="lf-part"><span>Otherwise <span class="hint small">for the other rows; blank: nothing</span></span>
								<input :value="r.calc.otherwise" placeholder="e.g. 0" :class="{ invalid: fieldError(i, 'otherwise') }"
									@input="r.calc.otherwise = ($event.target as HTMLInputElement).value" @focus="track($event, (v) => (r.calc.otherwise = v))" /></label>
							<label class="lf-part lf-dec"><span>Decimals</span>
								<input type="number" min="0" max="10" :value="r.calc.decimals ?? ''" placeholder="as is"
									@input="r.calc.decimals = ($event.target as HTMLInputElement).value === '' ? null : Number(($event.target as HTMLInputElement).value)" /></label>
						</div>
						<span v-if="fieldError(i, 'otherwise')" class="warn small">{{ fieldError(i, 'otherwise') }}</span>
						<div class="lf-part"><span>Checks on the answer <span class="hint small">each holds for a good answer; &lt;&lt;value&gt;&gt; is the answer</span></span>
							<div v-for="(c, n) in r.calc.checks" :key="n" class="lf-check">
								<input :value="c.rule" class="mono" placeholder="e.g. 0 < <<value>> <= 1" :aria-label="`Check ${n + 1}`" :class="{ invalid: fieldError(i, `checks.${n}`) }"
									@input="c.rule = ($event.target as HTMLInputElement).value" @focus="track($event, (v) => (c.rule = v))" />
								<input v-model="c.message" placeholder="Message when it fails" :aria-label="`Check ${n + 1} message`" />
								<select v-model="c.severity" :aria-label="`Check ${n + 1} severity`"><option value="error">error</option><option value="warning">warning</option></select>
								<button type="button" class="secondary small" :title="`Remove check ${n + 1}`" @click="r.calc.checks.splice(n, 1)">✕</button>
								<span v-if="fieldError(i, `checks.${n}`)" class="warn small">{{ fieldError(i, `checks.${n}`) }}</span>
							</div>
							<div><button type="button" class="secondary small" @click="r.calc.checks.push({ rule: '', message: '', severity: 'error' })">+ Add check</button></div>
						</div>
						<div class="row tight">
							<select aria-label="Insert a reference" title="Put a reference where you were typing" @change="insert(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
								<option value="">Insert a reference…</option>
								<option v-for="x in references(r)" :key="x.ref" :value="x.ref">{{ x.ref }} – {{ x.label }}</option>
							</select>
							<span class="hint small" :title="`Text functions, written after a text: ${view?.text_functions.join(', ')}`">
								Functions: {{ view?.functions.join(', ') }}. Operators + − * / ** %, comparisons, and/or/not, <code>A if condition else B</code>.
								A blank cell is '': write <code>(&lt;&lt;field&gt;&gt; or 0)</code> to count it as 0.
							</span>
							<span class="spacer" />
							<button type="button" class="secondary small" :disabled="previewing || !r.calc.formula.trim()" @click="runPreview(i)">▶ Try it on the Load List</button>
						</div>
						<div v-if="preview" class="lf-preview">
							<p class="hint small">{{ preview.total }} active row(s)<template v-if="preview.errors"> · <span class="warnText">{{ preview.errors }} error(s)</span></template><template
								v-if="preview.warnings"> · {{ preview.warnings }} warning(s)</template><template v-if="!preview.errors && !preview.warnings"> · no problems</template>. Not saved yet.</p>
							<table class="grid simple">
								<thead><tr><th>Tag</th><th>Answer</th><th>Problem</th></tr></thead>
								<tbody>
									<tr v-for="(p, n) in preview.rows.slice(0, 50)" :key="n">
										<td>{{ p.tag }}</td><td class="mono">{{ shown(p.value) }}</td>
										<td><span v-for="x in p.issues" :key="x.message" :class="x.severity === 'error' ? 'warnText' : 'hint'">{{ x.severity }}: {{ x.message }} </span></td>
									</tr>
								</tbody>
							</table>
						</div>
					</div>
				</li>
			</ol>
			<div class="row tight">
				<button type="button" class="secondary small" @click="add">+ Add field</button>
				<button type="button" class="secondary small" title="A field worked out for each row from a formula" @click="addCalc">+ Add calculated field</button>
				<span class="spacer" />
				<HistoryButton entity="load_fields" record-id="load-fields" label="Load List fields" />
			</div>
			<div v-if="confirm" class="mcol-confirm">
				<strong>Saving will:</strong>
				<ul>
					<li v-if="nothing(confirm)" class="hint">change nothing.</li>
					<li v-for="(v, k) in confirm.relabelled" :key="`r${k}`">rename {{ v[0] }} → {{ v[1] }} (its tag stays &lt;&lt;{{ k }}&gt;&gt;)</li>
					<li v-if="confirm.added.length">add {{ confirm.added.join(', ') }}</li>
					<li v-for="(v, k) in confirm.rekinded" :key="`k${k}`">make {{ k }} {{ KIND_NAMES[v[1] as Kind] }} instead of {{ KIND_NAMES[v[0] as Kind] }}</li>
					<li v-if="confirm.recalculated.length">change the calculation of {{ confirm.recalculated.join(', ') }}</li>
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
