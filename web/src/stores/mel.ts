import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { apiDelete, apiGet, apiPostBytes, apiPostJson, apiPostJsonForBlob, apiPut, runningInTauri } from '../lib/engine';
import type {
	CsvInspect, LoadListResult, PipelineResult, Recipe, RecipeDetail, RecipeSummary, RevisionInfo, Stage, TargetList,
} from '../lib/melTypes';
import { tableWizardStore } from './excelWizard';

export const useMelExcel = tableWizardStore('mel');

export type MelTab = 'overview' | 'columns' | 'rows' | 'text' | 'overrides' | 'custom' | 'auto' | 'mapping' | 'result';

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export const useMel = defineStore('mel', () => {
	const recipes = ref<RecipeSummary[]>([]);
	const saved = ref<Recipe | null>(null); // as stored
	const draft = ref<Recipe | null>(null); // being edited
	const revisions = ref<RevisionInfo[]>([]);
	const fields = ref<string[]>([]);
	const busy = ref(false);
	const error = ref<string | null>(null);
	const message = ref<string | null>(null);
	// Which editor is showing (UI state, not saved).
	const tab = ref<MelTab>('overview');

	const dirty = computed(() => !!draft.value && JSON.stringify(draft.value) !== JSON.stringify(saved.value));
	const latest = computed(() => revisions.value[0] ?? null);
	const base = computed(() => `/api/mel/recipes/${draft.value?.id}`);

	async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
		busy.value = true;
		error.value = null;
		try {
			return await fn();
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err);
			return undefined;
		} finally {
			busy.value = false;
		}
	}

	async function refreshList() {
		const list = await run(() => apiGet<RecipeSummary[]>('/api/mel/recipes'));
		if (list) recipes.value = list;
	}

	async function open(id: string) {
		const d = await run(() => apiGet<RecipeDetail>(`/api/mel/recipes/${id}`));
		if (!d) return;
		saved.value = d.recipe;
		draft.value = clone(d.recipe);
		revisions.value = d.revisions;
		fields.value = d.fields;
		message.value = null;
		tab.value = 'overview';
	}

	async function create(name: string, target: TargetList) {
		const r = await run(() => apiPostJson<Recipe>('/api/mel/recipes', { name, target }));
		if (r) {
			await open(r.id);
			await refreshList();
		}
	}

	function close() {
		saved.value = null;
		draft.value = null;
		revisions.value = [];
		void refreshList();
	}

	async function save() {
		if (!draft.value) return;
		const r = await run(() => apiPut<Recipe>(base.value, draft.value));
		if (r) {
			saved.value = r;
			draft.value = clone(r);
			message.value = 'Saved';
		}
	}

	function discard() {
		if (saved.value) draft.value = clone(saved.value);
	}

	async function remove(id: string) {
		await run(() => apiDelete(`/api/mel/recipes/${id}`));
		if (draft.value?.id === id) close();
		else await refreshList();
	}

	async function reloadRevisions() {
		const d = await run(() => apiGet<RecipeDetail>(base.value));
		if (d) revisions.value = d.revisions;
	}

	function inspectCsv(file: Blob) {
		return run(() => apiPostBytes<CsvInspect>('/api/mel/csv/inspect', file));
	}

	async function uploadCsv(file: Blob, filename: string, key: string) {
		const q = new URLSearchParams({ filename, key });
		const info = await run(() => apiPostBytes<RevisionInfo>(`${base.value}/revisions/csv?${q}`, file));
		if (info) await reloadRevisions();
		return info;
	}

	async function uploadExcel(spec: Record<string, unknown>) {
		const info = await run(() => apiPostJson<RevisionInfo>(`${base.value}/revisions/excel`, spec));
		if (info) await reloadRevisions();
		return info;
	}

	async function deleteRevision(id: string) {
		await run(() => apiDelete(`${base.value}/revisions/${id}`));
		await reloadRevisions();
	}

	/** Run the pipeline up to a stage with the current (unsaved) draft. */
	function runStage(stage: Stage) {
		return run(() => apiPostJson<PipelineResult>(`${base.value}/run`, { stage, recipe: draft.value }));
	}

	function loadList() {
		return run(() => apiPostJson<LoadListResult>(`${base.value}/loadlist`, { recipe: draft.value }));
	}

	async function exportTable(table: 'combined' | 'loadlist', format: 'csv' | 'xlsx') {
		if (!draft.value) return;
		const body = { table, format, recipe: draft.value };
		const name = `${draft.value.name} ${table === 'combined' ? 'combined' : 'load list'}.${format}`.replace(/[\\/:*?"<>|]+/g, '_');
		message.value = null;
		await run(async () => {
			if (runningInTauri) {
				const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
				const path = await saveDialog({
					defaultPath: name,
					filters: [format === 'csv' ? { name: 'CSV', extensions: ['csv'] } : { name: 'Excel workbook', extensions: ['xlsx'] }],
				});
				if (!path) return;
				const res = await apiPostJson<{ path: string }>(`${base.value}/export`, { ...body, path });
				message.value = `Saved ${res.path}`;
			} else {
				const blob = await apiPostJsonForBlob(`${base.value}/export`, body);
				const url = URL.createObjectURL(blob);
				Object.assign(document.createElement('a'), { href: url, download: name }).click();
				setTimeout(() => URL.revokeObjectURL(url), 10_000);
				message.value = `Downloaded ${name}`;
			}
		});
	}

	return {
		tab, recipes, saved, draft, revisions, fields, busy, error, message, dirty, latest,
		refreshList, open, create, close, save, discard, remove, inspectCsv, uploadCsv, uploadExcel,
		deleteRevision, runStage, loadList, exportTable,
	};
});
