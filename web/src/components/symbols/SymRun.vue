<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { apiGet } from '../../lib/engine';
import { TARGET_LABELS, TARGETS, type RecipeSummary, type TargetList } from '../../lib/melTypes';
import type { TagsTable } from '../../lib/symbolTypes';
import { useSymbols } from '../../stores/symbols';

const props = defineProps<{ runId: string }>();
const emit = defineEmits<{ 'open-import': [recipeId: string] }>();
const sym = useSymbols();

const run = computed(() => sym.runs.find((r) => r.id === props.runId) ?? null);
const finished = computed(() => !!run.value && !['queued', 'running'].includes(run.value.status));
const names = computed(() =>
	(run.value?.doc_ids ?? []).map((id) => sym.drawings.find((d) => d.id === id)?.file_name ?? '(deleted drawing)'),
);
const tags = ref<TagsTable | null>(null);
const host = ref<HTMLDivElement | null>(null);
const showWarnings = ref(false);
let table: FilteredTable<Record<string, string>> | null = null;

// Send to the list import
const sending = ref(false);
const recipes = ref<RecipeSummary[]>([]);
const target = ref<string>('');
const newName = ref('Instrument list');
const newTarget = ref<TargetList>('PIL');
const sent = ref<{ id: string; name: string } | null>(null);

async function load() {
	tags.value = null;
	sent.value = null;
	if (finished.value) tags.value = (await sym.runTags(props.runId)) ?? null;
}

function build() {
	table?.api.destroy();
	table = null;
	const t = tags.value;
	if (!host.value || !t) return;
	if (!t.rows.length) {
		host.value.innerHTML = '<p class="hint">No tags were found. Check the warnings above, add templates, or check the library\'s tag pattern.</p>';
		return;
	}
	const columns: ColumnsConfig[] = t.headers.map((h): ColumnsConfig => ({
		title: escapeHtml(h),
		data: (row: Record<string, string>) => row[h] ?? '',
		render: (v: unknown, type: string) => (type === 'display' ? escapeHtml(String(v ?? '')) : h === 'Count' ? Number(v) : v),
		className: h === 'Tag' ? 'key-col' : h === 'Count' ? 'dt-right' : '',
	}));
	const src = t.headers.indexOf('Source');
	table = createFilteredTable<Record<string, string>>(host.value, columns.length, {
		data: t.rows, columns, order: [[0, 'asc']], pageLength: 50, lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT, language: { search: 'Search all:' },
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible' } },
		],
	}, src < 0 ? {} : {
		[src]: {
			options: [{ value: '', label: 'All' }, { value: 'template', label: 'Template' }, { value: 'text scan', label: 'Text scan' }],
			test: (v, row) => !v || row.Source === v,
		},
	});
}

async function openSend() {
	sending.value = true;
	sent.value = null;
	recipes.value = await apiGet<RecipeSummary[]>('/api/mel/recipes');
	target.value = recipes.value.find((r) => r.target === 'PIL')?.id ?? '';
}

async function send() {
	const id = await sym.sendToImport(props.runId, target.value || null, newName.value, newTarget.value);
	if (id) {
		const r = recipes.value.find((x) => x.id === id);
		sent.value = { id, name: r?.name ?? newName.value };
		sending.value = false;
	}
}

function remove() {
	if (confirm('Delete this analysis run? The drawings and templates are kept.')) void sym.deleteRun(props.runId);
}

watch(() => [props.runId, finished.value], load, { immediate: true });
watch([tags, host], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<section v-if="run" class="card sym-main sym-run">
		<div class="mel-head">
			<h3>Analysis {{ run.started_at ? new Date(run.started_at).toLocaleString() : '' }}</h3>
			<span class="chip" :class="run.status">{{ run.status }}</span>
			<span class="chip" :title="names.join('\n')">{{ names.length }} drawing(s)</span>
			<span class="spacer" />
			<template v-if="finished && tags?.rows.length">
				<button type="button" class="secondary" :disabled="sym.busy" @click="sym.exportRun(run.id, 'xlsx')">Export .xlsx</button>
				<button type="button" class="secondary" :disabled="sym.busy" @click="sym.exportRun(run.id, 'csv')">Export .csv</button>
				<button type="button" :disabled="sym.busy" @click="openSend">Send to a list import…</button>
			</template>
			<button v-if="!finished" type="button" class="secondary" @click="sym.cancelRun(run.id)">Cancel</button>
			<button v-else type="button" class="secondary small" @click="remove">Delete</button>
		</div>

		<div v-if="!finished" class="sym-progress">
			<progress :value="run.done_steps" :max="run.total_steps || 1" />
			<span class="small">{{ run.done_steps }} / {{ run.total_steps }} pages · {{ run.current || 'waiting…' }}</span>
		</div>
		<p v-if="run.error" class="error">{{ run.error }}</p>
		<p v-if="sym.error" class="error">{{ sym.error }}</p>
		<p v-else-if="sym.message" class="saved">{{ sym.message }}</p>

		<div v-if="sending" class="sym-banner">
			<span>Add these {{ tags?.rows.length }} tags as the next file revision of</span>
			<select v-model="target" aria-label="Import">
				<option v-for="r in recipes" :key="r.id" :value="r.id">{{ r.name }} · {{ TARGET_LABELS[r.target] }} (rev {{ (r.latest_rev ?? 0) + 1 }})</option>
				<option value="">a new list import…</option>
			</select>
			<template v-if="!target">
				<input v-model="newName" placeholder="Import name" aria-label="New import name" />
				<select v-model="newTarget" aria-label="List type">
					<option v-for="t in TARGETS" :key="t" :value="t">{{ TARGET_LABELS[t] }}</option>
				</select>
			</template>
			<button type="button" class="small" :disabled="sym.busy" @click="send">Send</button>
			<button type="button" class="secondary small" @click="sending = false">Cancel</button>
		</div>
		<div v-if="sent" class="sym-banner ok">
			<span>✓ Sent to <strong>{{ sent.name }}</strong>. Its saved rules (columns, overrides, calculated columns, mapping) re-apply to the new tags.</span>
			<button type="button" class="small" @click="emit('open-import', sent.id)">Open it in List import</button>
		</div>

		<div v-if="run.warnings.length" class="sym-warnings">
			<button type="button" class="link small" @click="showWarnings = !showWarnings">
				{{ showWarnings ? '▾' : '▸' }} {{ run.warnings.length }} warning(s)
			</button>
			<ul v-if="showWarnings"><li v-for="(w, i) in run.warnings" :key="i" class="warn small">{{ w }}</li></ul>
		</div>

		<div v-if="finished" class="results">
			<p class="hint small">
				One row per tag. <strong>Template</strong> tags were read from matched symbols; <strong>text scan</strong> tags are
				text matching the library's tag pattern elsewhere on the sheet. Repeats across sheets are counted.
			</p>
			<div ref="host" class="result-table" />
		</div>
	</section>
</template>
