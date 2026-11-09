<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { apiGet } from '../../lib/engine';
import type { RecipeSummary } from '../../lib/melTypes';
import type { TagsTable } from '../../lib/pidTypes';
import { usePid } from '../../stores/pid';

const props = defineProps<{ runId: string }>();
const emit = defineEmits<{ 'open-import': [recipeId: string] }>();
const pid = usePid();

const run = computed(() => pid.runs.find((r) => r.id === props.runId) ?? null);
const finished = computed(() => !!run.value && !['queued', 'running'].includes(run.value.status));
const names = computed(() =>
	(run.value?.doc_ids ?? []).map((id) => pid.drawings.find((d) => d.id === id)?.file_name ?? '(deleted drawing)'),
);
const tags = ref<TagsTable | null>(null);
const host = ref<HTMLDivElement | null>(null);
const showWarnings = ref(false);
let table: FilteredTable<Record<string, string>> | null = null;

// Send to the list import
const sending = ref(false);
const pilRecipes = ref<RecipeSummary[]>([]);
const target = ref<string>('');
const newName = ref('Instrument list');
const sent = ref<{ id: string; name: string } | null>(null);

async function load() {
	tags.value = null;
	sent.value = null;
	if (finished.value) tags.value = (await pid.runTags(props.runId)) ?? null;
}

function build() {
	table?.api.destroy();
	table = null;
	const t = tags.value;
	if (!host.value || !t) return;
	if (!t.rows.length) {
		host.value.innerHTML = '<p class="hint">No tags were found. Check the warnings above, add templates, or look at the tag pattern in Settings.</p>';
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
			options: [{ value: '', label: 'All' }, { value: 'template', label: 'Template' }, { value: 'pattern', label: 'Text scan' }],
			test: (v, row) => !v || row.Source === v,
		},
	});
}

async function openSend() {
	sending.value = true;
	sent.value = null;
	pilRecipes.value = (await apiGet<RecipeSummary[]>('/api/mel/recipes')).filter((r) => r.target === 'PIL');
	target.value = pilRecipes.value[0]?.id ?? '';
}

async function send() {
	const id = await pid.sendToImport(props.runId, target.value || null, newName.value);
	if (id) {
		const r = pilRecipes.value.find((x) => x.id === id);
		sent.value = { id, name: r?.name ?? newName.value };
		sending.value = false;
	}
}

function remove() {
	if (confirm('Delete this analysis run? The drawings and templates are kept.')) void pid.deleteRun(props.runId);
}

watch(() => [props.runId, finished.value], load, { immediate: true });
watch([tags, host], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<section v-if="run" class="card pid-main pid-run">
		<div class="mel-head">
			<h3>Analysis {{ run.started_at ? new Date(run.started_at).toLocaleString() : '' }}</h3>
			<span class="chip" :class="run.status">{{ run.status }}</span>
			<span class="chip" :title="names.join('\n')">{{ names.length }} drawing(s)</span>
			<span class="spacer" />
			<template v-if="finished && tags?.rows.length">
				<button type="button" class="secondary" :disabled="pid.busy" @click="pid.exportRun(run.id, 'xlsx')">Export .xlsx</button>
				<button type="button" class="secondary" :disabled="pid.busy" @click="pid.exportRun(run.id, 'csv')">Export .csv</button>
				<button type="button" :disabled="pid.busy" @click="openSend">Send to instrument list import…</button>
			</template>
			<button v-if="!finished" type="button" class="secondary" @click="pid.cancelRun(run.id)">Cancel</button>
			<button v-else type="button" class="secondary small" @click="remove">Delete</button>
		</div>

		<div v-if="!finished" class="pid-progress">
			<progress :value="run.done_steps" :max="run.total_steps || 1" />
			<span class="small">{{ run.done_steps }} / {{ run.total_steps }} pages · {{ run.current || 'waiting…' }}</span>
		</div>
		<p v-if="run.error" class="error">{{ run.error }}</p>
		<p v-if="pid.error" class="error">{{ pid.error }}</p>
		<p v-else-if="pid.message" class="saved">{{ pid.message }}</p>

		<div v-if="sending" class="pid-banner">
			<span>Add these {{ tags?.rows.length }} tags as the next file revision of</span>
			<select v-model="target" aria-label="Import">
				<option v-for="r in pilRecipes" :key="r.id" :value="r.id">{{ r.name }} (rev {{ (r.latest_rev ?? 0) + 1 }})</option>
				<option value="">a new instrument list import…</option>
			</select>
			<input v-if="!target" v-model="newName" placeholder="Import name" aria-label="New import name" />
			<button type="button" class="small" :disabled="pid.busy" @click="send">Send</button>
			<button type="button" class="secondary small" @click="sending = false">Cancel</button>
		</div>
		<div v-if="sent" class="pid-banner ok">
			<span>✓ Sent to <strong>{{ sent.name }}</strong>. Its saved rules (columns, overrides, calculated columns, mapping) re-apply to the new tags.</span>
			<button type="button" class="small" @click="emit('open-import', sent.id)">Open it in List import</button>
		</div>

		<div v-if="run.warnings.length" class="pid-warnings">
			<button type="button" class="link small" @click="showWarnings = !showWarnings">
				{{ showWarnings ? '▾' : '▸' }} {{ run.warnings.length }} warning(s)
			</button>
			<ul v-if="showWarnings"><li v-for="(w, i) in run.warnings" :key="i" class="warn small">{{ w }}</li></ul>
		</div>

		<div v-if="finished" class="results">
			<p class="hint small">
				One row per tag. <strong>Template</strong> tags were read from matched symbols; <strong>text scan</strong> tags are
				ISA-style text found anywhere on the sheet. Repeats across sheets are counted.
			</p>
			<div ref="host" class="result-table" />
		</div>
	</section>
</template>
