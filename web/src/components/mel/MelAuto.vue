<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { AutoColumn, PipelineResult } from '../../lib/melTypes';
import { useStage } from '../../lib/useStage';
import { useMel } from '../../stores/mel';

const mel = useMel();
// Calculated columns run last and can read every column, including custom rows.
const { result: base } = useStage('custom', (r) => [r.columns, r.hidden_rows, r.text_columns, r.overrides, r.custom_rows]);
const selected = ref<number | null>(mel.draft!.auto_columns.length ? 0 : null);
const preview = ref<PipelineResult | null>(null);
const lastField = ref<keyof AutoColumn>('statement');
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
	mel.draft!.auto_columns.push({ name: `Calc ${n}`, statement: 'True', true_val: '', false_val: '', error_val: 'ERROR' });
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

/** Insert <<column>> at the cursor of the last focused field. */
function insert() {
	const c = col.value;
	if (!c || !pickCol.value) return;
	const field = lastField.value;
	const el = inputs.value[field];
	const text = String(c[field] ?? '');
	const ref_ = `<<${pickCol.value}>>`;
	const at = el?.selectionStart ?? text.length;
	(c[field] as string) = text.slice(0, at) + ref_ + text.slice(el?.selectionEnd ?? at);
	requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(at + ref_.length, at + ref_.length); });
}

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
	for (const s of [c.statement, c.true_val, c.false_val]) for (const m of s.matchAll(/<<(.+?)>>/g)) found.add(m[1]);
	return [...found];
});
const errors = computed(() => (col.value ? (preview.value?.rows.filter((r) => r.auto_errors.includes(col.value!.name)).length ?? 0) : 0));
const issues = computed(() => preview.value?.issues.filter((i) => i.kind === 'auto') ?? []);
</script>

<template>
	<div class="auto">
		<p class="hint">
			A calculated column checks a condition on every row and writes one of two results. Refer to a column as
			<code>&lt;&lt;Column name&gt;&gt;</code>; numbers are numbers and text is text, no quotes needed. Examples:
			<code>&lt;&lt;Equipment Type&gt;&gt; == 'Pump'</code>,
			<code>round(&lt;&lt;Motor HP&gt;&gt; * 0.746, 1)</code>. Columns run top to bottom, so one can use another's result.
			Plain text such as <code>Motor</code> is used as is.
		</p>
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
				<label class="field">If (condition)
					<input :ref="(el) => (inputs.statement = el as HTMLInputElement)" v-model="col.statement" class="mono" @focus="lastField = 'statement'" />
				</label>
				<div class="row">
					<label class="field grow">Then
						<input :ref="(el) => (inputs.true_val = el as HTMLInputElement)" v-model="col.true_val" class="mono" @focus="lastField = 'true_val'" />
					</label>
					<label class="field grow">Else
						<input :ref="(el) => (inputs.false_val = el as HTMLInputElement)" v-model="col.false_val" class="mono" @focus="lastField = 'false_val'" />
					</label>
					<label class="field">On error <input v-model="col.error_val" class="mono" /></label>
				</div>
				<div class="row">
					<select v-model="pickCol" aria-label="Column to insert">
						<option value="" disabled>Insert a column…</option>
						<option v-for="h in available" :key="h" :value="h">{{ h }}</option>
					</select>
					<button type="button" class="secondary small" :disabled="!pickCol" @click="insert">Insert into "{{ { statement: 'If', true_val: 'Then', false_val: 'Else', name: '', error_val: '' }[lastField] }}"</button>
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
