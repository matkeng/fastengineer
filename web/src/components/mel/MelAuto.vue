<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { apiGet } from '../../lib/engine';
import type { AutoBranch, PipelineResult } from '../../lib/melTypes';
import { useStage } from '../../lib/useStage';
import { useMel } from '../../stores/mel';

const mel = useMel();
// Calculated columns run last and can read every column, including custom rows.
const { result: base } = useStage('replace', (r) => [r.columns, r.hidden_rows, r.text_columns, r.overrides, r.custom_rows, r.find_replace]);
const selected = ref<number | null>(mel.draft!.auto_columns.length ? 0 : null);
const preview = ref<PipelineResult | null>(null);
// The field a column is inserted into: 'statement', 'true_val', 'false_val', or 'b<i>.statement' / 'b<i>.value' for an Else if.
const lastField = ref('statement');
const pickCol = ref('');
const inputs = ref<Record<string, HTMLInputElement | null>>({});

const col = computed(() => (selected.value === null ? null : mel.draft!.auto_columns[selected.value]));
// Columns available to the selected calculation: the table + earlier calculated columns.
const available = computed(() => [
	...(base.value?.headers ?? []),
	...mel.draft!.auto_columns.slice(0, selected.value ?? 0).map((a) => a.name),
]);

function add() {
	let n = 1;
	while (mel.draft!.auto_columns.some((a) => a.name === `Calc ${n}`)) n++;
	mel.draft!.auto_columns.push({ name: `Calc ${n}`, statement: 'True', negate: false, true_val: '', else_ifs: [], false_val: '', error_val: 'ERROR' });
	selected.value = mel.draft!.auto_columns.length - 1;
}

function move(i: number, d: -1 | 1) {
	const list = mel.draft!.auto_columns;
	const j = i + d;
	if (j < 0 || j >= list.length) return;
	[list[i], list[j]] = [list[j], list[i]];
	if (selected.value === i) selected.value = j;
}

function remove(i: number) {
	if (!confirm(`Delete calculated column ${mel.draft!.auto_columns[i].name}?`)) return;
	mel.draft!.auto_columns.splice(i, 1);
	selected.value = mel.draft!.auto_columns.length ? Math.min(i, mel.draft!.auto_columns.length - 1) : null;
}

// -- Else if branches: tried in order after the If; the first that holds gives the value ----------
const branches = computed<AutoBranch[]>(() => (col.value ? (col.value.else_ifs ??= []) : []));
function addBranch() {
	branches.value.push({ statement: '', negate: false, value: '' });
	lastField.value = `b${branches.value.length - 1}.statement`;
	requestAnimationFrame(() => inputs.value[lastField.value]?.focus());
}
function moveBranch(i: number, d: -1 | 1) {
	const list = branches.value;
	const j = i + d;
	if (j >= 0 && j < list.length) [list[i], list[j]] = [list[j], list[i]];
}
const removeBranch = (i: number) => branches.value.splice(i, 1);

/** Read or write the field `key` names (see lastField). */
function fieldText(key: string, value?: string): string {
	const c = col.value!;
	const m = /^b(\d+)\.(statement|value)$/.exec(key);
	const target = (m ? branches.value[Number(m[1])] : c) as unknown as Record<string, string> | undefined;
	const name = m ? m[2] : key;
	if (!target) return '';
	if (value !== undefined) target[name] = value;
	return String(target[name] ?? '');
}
const fieldLabel = computed(() => {
	const m = /^b(\d+)\.(statement|value)$/.exec(lastField.value);
	if (m) return `Else if ${Number(m[1]) + 1}: ${m[2] === 'statement' ? 'condition' : 'then'}`;
	return ({ statement: 'If', true_val: 'Then', false_val: 'Else' } as Record<string, string>)[lastField.value] ?? '';
});

/** Insert <<column>> at the cursor of the last focused field. */
function insert() {
	if (pickCol.value) insertText(`<<${pickCol.value}>>`);
}

/** Insert some text at the cursor of the last focused field (If, Then, an Else if, Else). */
function insertText(ref_: string) {
	if (!col.value || !fieldLabel.value) return;
	const field = lastField.value;
	const el = inputs.value[field];
	const text = fieldText(field);
	const at = el?.selectionStart ?? text.length;
	fieldText(field, text.slice(0, at) + ref_ + text.slice(el?.selectionEnd ?? at));
	requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(at + ref_.length, at + ref_.length); });
}

// -- help: the text and number functions, with examples worked out on a sample row ----------------
interface FunctionHelp {
	sample_row: Record<string, string>;
	groups: { name: string; about: string; examples: { expression: string; result: string; what: string }[] }[];
	functions: string[];
	text_functions: string[];
	names: string[];
}
const help = ref<FunctionHelp | null>(null);
const helpOpen = ref(false);
const helpFilter = ref('');
const shownGroups = computed(() => {
	const q = helpFilter.value.trim().toLowerCase();
	const groups = help.value?.groups ?? [];
	if (!q) return groups;
	return groups.map((g) => ({ ...g, examples: g.examples.filter((e) => `${e.expression} ${e.what}`.toLowerCase().includes(q)) }))
		.filter((g) => g.examples.length);
});
const sampleText = computed(() => Object.entries(help.value?.sample_row ?? {}).map(([k, v]) => `${k} = '${v}'`).join(', '));
onMounted(async () => {
	help.value = await apiGet<FunctionHelp>('/api/mel/functions').catch(() => null);
});

let timer: ReturnType<typeof setTimeout> | undefined;
watch(
	() => JSON.stringify(mel.draft!.auto_columns),
	() => { clearTimeout(timer); timer = setTimeout(async () => { preview.value = (await mel.runStage('auto')) ?? null; }, 400); },
	{ immediate: true },
);

const sampleRows = computed(() => preview.value?.rows.slice(0, 12) ?? []);
const refs = computed(() => {
	const c = col.value;
	if (!c) return [];
	const found = new Set<string>();
	const texts = [c.statement, c.true_val, ...(c.else_ifs ?? []).flatMap((b) => [b.statement, b.value]), c.false_val];
	for (const s of texts) for (const m of (s ?? '').matchAll(/<<(.+?)>>/g)) found.add(m[1]);
	return [...found];
});
const errors = computed(() => (col.value ? (preview.value?.rows.filter((r) => r.auto_errors.includes(col.value!.name)).length ?? 0) : 0));
const issues = computed(() => preview.value?.issues.filter((i) => i.kind === 'auto') ?? []);
</script>

<template>
	<div class="auto">
		<p class="hint">
			A calculated column checks conditions on every row, in order: <strong>If</strong>, then each <strong>Else if</strong>;
			the first that holds gives the value, and if none does the row gets the <strong>Else</strong> value. Tick
			<strong>NOT</strong> to use the opposite of a condition. Refer to a column as
			<code>&lt;&lt;Column name&gt;&gt;</code>; numbers are numbers and text is text, no quotes needed. Examples:
			<code>&lt;&lt;Equipment Type&gt;&gt; == 'Pump'</code>,
			<code>round(&lt;&lt;Motor HP&gt;&gt; * 0.746, 1)</code>. Columns run top to bottom, so one can use another's result.
			Plain text such as <code>Motor</code> is used as is.
			<button type="button" class="link" :aria-expanded="helpOpen" @click="helpOpen = !helpOpen">{{ helpOpen ? 'Hide' : 'Show' }} the functions you can use</button>
		</p>
		<section v-if="helpOpen" class="func-help" aria-label="Functions you can use">
			<div class="row">
				<strong>Functions and examples</strong>
				<input v-model="helpFilter" type="search" class="func-filter" placeholder="Find a function, e.g. round, upper, split…" aria-label="Find a function" />
				<span class="hint small">Results are for a sample row: {{ sampleText }}.
					<template v-if="col">Click an example to insert it into “{{ fieldLabel || 'If' }}”.</template></span>
				<span class="spacer" />
				<button type="button" class="secondary small" @click="helpOpen = false">Close</button>
			</div>
			<p v-if="!help" class="hint">Loading…</p>
			<p v-else class="func-allowed small">
				<strong>Only these can be used.</strong> Anything else (other functions, <code>.</code> names, <code>import</code>, files) is refused, and the column shows its On error value.<br />
				Functions: <code v-for="f in help.functions" :key="f">{{ f }}()</code><br />
				Text functions, after a text value: <code v-for="f in help.text_functions" :key="f">.{{ f }}()</code><br />
				Names: <code v-for="n in help.names" :key="n">{{ n }}</code> and your columns as <code>&lt;&lt;Column&gt;&gt;</code>.
				Operators: <code>+ - * / // % **</code> <code>== != &lt; &lt;= &gt; &gt;=</code> <code>in</code> <code>not in</code> <code>and or not</code> <code>x if c else y</code> <code>[i]</code> <code>[a:b]</code>.
			</p>
			<div class="func-groups">
				<div v-for="g in shownGroups" :key="g.name" class="func-group">
					<h4>{{ g.name }}</h4>
					<p class="hint small">{{ g.about }}</p>
					<table class="grid simple func-table">
						<tbody>
							<tr v-for="e in g.examples" :key="e.expression">
								<td class="expr">
									<button type="button" class="link mono" :disabled="!col" :title="col ? 'Insert into the field you were last in' : 'Add or pick a calculated column first'"
										@click="insertText(e.expression)">{{ e.expression }}</button>
								</td>
								<td class="res mono" title="What the sample row gives">→ {{ e.result }}</td>
								<td class="what">{{ e.what }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
			<p class="hint small">Not available: <code>.format()</code> (use <code>'%.1f' % value</code>), and anything that reads files or the network.</p>
		</section>
		<div class="two-col auto-cols">
			<div>
				<ul class="auto-list">
					<li v-for="(a, i) in mel.draft!.auto_columns" :key="i" :class="{ current: selected === i }" @click="selected = i">
						<span class="num">{{ i + 1 }}</span>
						<span class="name">{{ a.name }}</span>
						<button type="button" class="secondary small" :disabled="i === 0" title="Move up" @click.stop="move(i, -1)">↑</button>
						<button type="button" class="secondary small" :disabled="i === mel.draft!.auto_columns.length - 1" title="Move down" @click.stop="move(i, 1)">↓</button>
						<button type="button" class="secondary small" title="Delete" @click.stop="remove(i)">✕</button>
					</li>
				</ul>
				<button type="button" @click="add">Add calculated column</button>
			</div>
			<div v-if="col" class="auto-edit">
				<label class="field">Column name <input v-model="col.name" /></label>
				<div class="cases">
					<div class="case">
						<span class="case-word">If</span>
						<label class="not" title="Use the opposite of this condition"><input v-model="col.negate" type="checkbox" /> NOT</label>
						<input :ref="(el) => (inputs.statement = el as HTMLInputElement)" v-model="col.statement" class="mono cond"
							aria-label="If condition" placeholder="condition, e.g. <<Type>> == 'Pump'" @focus="lastField = 'statement'" />
						<span class="case-word">then</span>
						<input :ref="(el) => (inputs.true_val = el as HTMLInputElement)" v-model="col.true_val" class="mono val"
							aria-label="If value" @focus="lastField = 'true_val'" />
						<span class="case-tools" />
					</div>
					<div v-for="(b, bi) in branches" :key="bi" class="case">
						<span class="case-word">Else if</span>
						<label class="not" title="Use the opposite of this condition"><input v-model="b.negate" type="checkbox" /> NOT</label>
						<input :ref="(el) => (inputs[`b${bi}.statement`] = el as HTMLInputElement)" v-model="b.statement" class="mono cond"
							:aria-label="`Else if ${bi + 1} condition`" placeholder="condition" @focus="lastField = `b${bi}.statement`" />
						<span class="case-word">then</span>
						<input :ref="(el) => (inputs[`b${bi}.value`] = el as HTMLInputElement)" v-model="b.value" class="mono val"
							:aria-label="`Else if ${bi + 1} value`" @focus="lastField = `b${bi}.value`" />
						<span class="case-tools">
							<button type="button" class="secondary small" :disabled="bi === 0" title="Move up" @click="moveBranch(bi, -1)">↑</button>
							<button type="button" class="secondary small" :disabled="bi === branches.length - 1" title="Move down" @click="moveBranch(bi, 1)">↓</button>
							<button type="button" class="secondary small" title="Remove this Else if" @click="removeBranch(bi)">✕</button>
						</span>
					</div>
					<div class="case add-case">
						<button type="button" class="secondary small" @click="addBranch">+ Else if</button>
					</div>
					<div class="case">
						<span class="case-word">Else</span>
						<span class="not" />
						<input :ref="(el) => (inputs.false_val = el as HTMLInputElement)" v-model="col.false_val" class="mono val wide"
							aria-label="Else value" @focus="lastField = 'false_val'" />
						<span class="case-tools" />
					</div>
					<div class="case">
						<span class="case-word">On error</span>
						<span class="not" />
						<input v-model="col.error_val" class="mono val wide" aria-label="Value on error"
							title="Written when a condition or value can't be worked out for a row" />
						<span class="case-tools" />
					</div>
				</div>
				<div class="row">
					<select v-model="pickCol" aria-label="Column to insert">
						<option value="" disabled>Insert a column…</option>
						<option v-for="h in available" :key="h" :value="h">{{ h }}</option>
					</select>
					<button type="button" class="secondary small" :disabled="!pickCol || !fieldLabel" @click="insert">Insert into "{{ fieldLabel }}"</button>
				</div>
				<p v-for="i in issues" :key="i.rule + i.message" class="warn small">{{ i.rule }}: {{ i.message }}</p>
				<h4>Preview <span class="hint">({{ errors }} error{{ errors === 1 ? '' : 's' }} of {{ preview?.rows.length ?? 0 }} rows)</span></h4>
				<div class="grid-wrap small-grid">
					<table class="grid">
						<thead><tr><th>{{ preview?.key_header }}</th><th v-for="h in refs" :key="h">{{ h }}</th><th class="calc-col">{{ col.name }}</th></tr></thead>
						<tbody>
							<tr v-for="r in sampleRows" :key="r.key">
								<td>{{ r.key }}</td>
								<td v-for="h in refs" :key="h">{{ r.values[h] }}</td>
								<td class="calc-col" :class="{ err: r.auto_errors.includes(col.name) }">{{ r.values[col.name] }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</div>
</template>
