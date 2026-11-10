// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { apiDelete, apiGet, apiPostBytes, apiPostJson, apiPostJsonForBlob, apiPut, exportToPath, runningInTauri } from '../lib/engine';
import type {
	BuildInfo, BuildRecord, InputsImport, CheckResult, GenRecord, GenSummary, HardwareView, ImportReport, PreviewResult,
} from '../lib/genTypes';

export type GenTab = 'runsheet' | 'templates' | 'check' | 'build' | 'hardware' | 'settings';

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export const useGenerators = defineStore('generators', () => {
	const list = ref<GenSummary[]>([]);
	const saved = ref<GenRecord | null>(null);
	const draft = ref<GenRecord | null>(null);
	const builds = ref<BuildInfo[]>([]);
	const build = ref<BuildRecord | null>(null); // the build shown on the Build tab
	const checkResult = ref<CheckResult | null>(null);
	const lastImport = ref<ImportReport | null>(null);
	const busy = ref(false);
	const error = ref<string | null>(null);
	const fieldErrors = ref<Record<string, string>>({});
	const message = ref<string | null>(null);
	const tab = ref<GenTab>('runsheet');
	const selectedTemplate = ref<string | null>(null); // on the Templates tab
	const jumpToRow = ref<string | null>(null); // a runsheet row to scroll to (from Check)

	const dirty = computed(() => !!draft.value && JSON.stringify(draft.value) !== JSON.stringify(saved.value));
	// PLC hardware register of the open generator, and the shared type catalogue (saved separately)
	const hwView = ref<HardwareView | null>(null);
	const anyDirty = computed(() => dirty.value);
	const base = computed(() => `/api/generators/${draft.value?.id}`);

	async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
		busy.value = true;
		error.value = null;
		fieldErrors.value = {};
		try {
			return await fn();
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err);
			fieldErrors.value = (err as { fields?: Record<string, string> }).fields ?? {};
			return undefined;
		} finally {
			busy.value = false;
		}
	}

	async function refreshList() {
		const l = await run(() => apiGet<GenSummary[]>('/api/generators'));
		if (l) list.value = l;
	}

	async function importWorkbook(file: File) {
		const q = new URLSearchParams({ filename: file.name });
		const res = await run(() => apiPostBytes<{ record: GenRecord; report: ImportReport }>(`/api/generators/import?${q}`, file));
		if (!res) return;
		lastImport.value = res.report;
		await refreshList();
		await open(res.record.id);
	}

	async function open(id: string) {
		const r = await run(() => apiGet<GenRecord>(`/api/generators/${id}`));
		if (!r) return;
		saved.value = r;
		draft.value = clone(r);
		checkResult.value = null;
		build.value = null;
		message.value = null;
		tab.value = 'runsheet';
		selectedTemplate.value = r.generator.templates[0]?.id ?? null;
		await loadBuilds(true);
		hwView.value = null;
		void loadHardware();
		void check();
	}

	function close() {
		saved.value = null;
		draft.value = null;
		hwView.value = null;
		builds.value = [];
		build.value = null;
		checkResult.value = null;
		void refreshList();
	}

	async function save() {
		if (!draft.value) return;
		const r = await run(() => apiPut<GenRecord>(base.value, { name: draft.value!.name, generator: draft.value!.generator }));
		if (r) {
			saved.value = r;
			draft.value = clone(r);
			message.value = 'Saved';
			void check();
		}
	}

	function discard() {
		if (saved.value) draft.value = clone(saved.value);
	}

	async function remove(id: string) {
		await run(() => apiDelete(`/api/generators/${id}`));
		if (draft.value?.id === id) close();
		else await refreshList();
	}

	/** Check the current draft (unsaved edits included). */
	async function check() {
		if (!draft.value) return;
		const r = await run(() => apiPostJson<CheckResult>(`${base.value}/check`, { draft: draft.value!.generator }));
		if (r) checkResult.value = r;
	}

	function preview(runRowId: string, templateId: string | null) {
		return run(() => apiPostJson<PreviewResult>(`${base.value}/preview`, {
			run_row_id: runRowId, template_id: templateId, draft: draft.value!.generator,
		}));
	}

	async function loadBuilds(showLatest = false) {
		const l = await run(() => apiGet<BuildInfo[]>(`${base.value}/builds`));
		if (!l) return;
		builds.value = l;
		if (showLatest && l.length) await loadBuild(l[0].id);
	}

	async function loadBuild(id: string) {
		const b = await run(() => apiGet<BuildRecord>(`/api/generators/builds/${id}`));
		if (b) build.value = b;
	}

	/** Build the saved generator (save first if there are edits). */
	async function startBuild(runFrom: number | null, runUpTo: number | null) {
		if (!draft.value) return;
		if (dirty.value) {
			await save();
			if (dirty.value) return; // save failed
		}
		const body = { run_from: runFrom, run_up_to: runUpTo, use_config_range: false };
		const info = await run(() => apiPostJson<BuildInfo>(`${base.value}/builds`, body));
		if (!info) return;
		await loadBuilds();
		await loadBuild(info.id);
		message.value = `Build ${info.seq}: ${info.stats.rows_written} rows`;
	}

	async function deleteBuild(id: string) {
		await run(() => apiDelete(`/api/generators/builds/${id}`));
		if (build.value?.info.id === id) build.value = null;
		await loadBuilds(!build.value);
	}

	async function exportBuild(format: 'xlsx' | 'csv') {
		const b = build.value;
		if (!b) return;
		const url = `/api/generators/builds/${b.info.id}/export`;
		message.value = null;
		await run(async () => {
			const { name } = await apiGet<{ name: string }>(`/api/generators/builds/${b.info.id}/name`, { format });
			if (runningInTauri) {
				const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
				const path = await saveDialog({
					defaultPath: name,
					filters: [format === 'csv' ? { name: 'CSV', extensions: ['csv'] } : { name: 'Excel workbook', extensions: ['xlsx'] }],
				});
				if (!path) return;
				const res = await exportToPath(url, { format }, path);
				message.value = `Saved ${res.path}`;
			} else {
				const blob = await apiPostJsonForBlob(url, { format });
				const href = URL.createObjectURL(blob);
				Object.assign(document.createElement('a'), { href, download: name }).click();
				setTimeout(() => URL.revokeObjectURL(href), 10_000);
				message.value = `Downloaded ${name}`;
			}
		});
	}

	// -- PLC hardware: read-only here (the register is the project's PLC List) -----------

	async function loadHardware() {
		const v = await run(() => apiGet<HardwareView>(`${base.value}/hardware`));
		if (v) hwView.value = v;
	}

	// -- bulk editing in Excel ---------------------------------------------------------

	async function exportInputs() {
		if (!draft.value) return;
		const url = `${base.value}/inputs/export`;
		const name = `${draft.value.name} inputs.xlsx`.replace(/[\\/:*?"<>|]+/g, '_');
		message.value = null;
		await run(async () => {
			if (runningInTauri) {
				const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
				const path = await saveDialog({ defaultPath: name, filters: [{ name: 'Excel workbook', extensions: ['xlsx'] }] });
				if (!path) return;
				const res = await exportToPath(url, {}, path);
				message.value = `Saved ${res.path}`;
			} else {
				const blob = await apiPostJsonForBlob(url, {});
				const href = URL.createObjectURL(blob);
				Object.assign(document.createElement('a'), { href, download: name }).click();
				setTimeout(() => URL.revokeObjectURL(href), 10_000);
				message.value = `Downloaded ${name}`;
			}
		});
	}

	/** Preview (no tables) or apply the chosen tables of an edited inputs workbook. */
	async function importInputs(file: File, tables: string[] = []) {
		const q = new URLSearchParams({ filename: file.name, apply: tables.join(',') });
		const res = await run(() => apiPostBytes<InputsImport>(`${base.value}/inputs/import?${q}`, file));
		if (res?.record) {
			saved.value = res.record;
			draft.value = clone(res.record);
			message.value = `Imported ${tables.length} sheet${tables.length === 1 ? '' : 's'}`;
			void check();
		}
		return res;
	}

	return {
		exportInputs, importInputs,
		hwView, anyDirty, loadHardware,
		list, saved, draft, builds, build, checkResult, lastImport, busy, error, fieldErrors, message, tab, dirty,
		selectedTemplate, jumpToRow,
		refreshList, importWorkbook, open, close, save, discard, remove, check, preview, loadBuilds, loadBuild,
		startBuild, deleteBuild, exportBuild,
	};
});
