import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import {
	ApiError, apiDelete, apiGet, apiGetBlob, apiPostBytes, apiPostJson, apiPostJsonForBlob, apiPut, runningInTauri,
} from '../lib/engine';
import type {
	Drawing, Library, OcrStatus, PageOverride, PageResult, RunInfo, Settings, TagsTable, Template, TestResult,
} from '../lib/pidTypes';

export type PidView =
	| { kind: 'none' }
	| { kind: 'drawing'; id: string; page: number }
	| { kind: 'template'; id: string }
	| { kind: 'run'; id: string }
	| { kind: 'settings' };

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export const usePid = defineStore('pid', () => {
	const drawings = ref<Drawing[]>([]);
	const templates = ref<Template[]>([]); // all libraries, in priority order
	const libraries = ref<Library[]>([]);
	const runs = ref<RunInfo[]>([]);
	const settings = ref<Settings | null>(null);
	const ocr = ref<OcrStatus | null>(null);
	const view = ref<PidView>({ kind: 'none' });
	const checked = ref<string[]>([]); // drawings ticked for the next run
	const busy = ref(false);
	const error = ref<string | null>(null);
	const fieldErrors = ref<Record<string, string>>({});
	const message = ref<string | null>(null);
	// Template editor
	const templateSaved = ref<Template | null>(null);
	const templateDraft = ref<Template | null>(null);
	// A template test shown on the page viewer
	const test = ref<{ template: Template; doc: string; page: number; result: TestResult } | null>(null);
	// The page last looked at: where "Test" runs
	const lastPage = ref<{ id: string; page: number } | null>(null);

	const templateDirty = computed(
		() => !!templateDraft.value && JSON.stringify(templateDraft.value) !== JSON.stringify(templateSaved.value),
	);
	const dirty = templateDirty;
	const anyRendering = computed(() => drawings.value.some((d) => d.status === 'rendering'));
	const activeRun = computed(() => runs.value.find((r) => r.status === 'queued' || r.status === 'running') ?? null);

	async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
		busy.value = true;
		error.value = null;
		fieldErrors.value = {};
		message.value = null;
		try {
			return await fn();
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err);
			if (err instanceof ApiError) fieldErrors.value = err.fields;
			return undefined;
		} finally {
			busy.value = false;
		}
	}

	async function refresh() {
		try {
			const [d, t, l, r] = await Promise.all([
				apiGet<Drawing[]>('/api/pid/drawings'),
				apiGet<Template[]>('/api/pid/templates'),
				apiGet<Library[]>('/api/pid/libraries'),
				apiGet<RunInfo[]>('/api/pid/runs'),
			]);
			drawings.value = d;
			templates.value = t;
			libraries.value = l;
			runs.value = r;
			checked.value = checked.value.filter((id) => d.some((x) => x.id === id));
			settings.value ??= await apiGet<Settings>('/api/pid/settings');
			ocr.value ??= await apiGet<OcrStatus>('/api/pid/ocr');
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err);
		}
		schedulePoll();
	}

	// Poll while something is rendering or running.
	let timer: ReturnType<typeof setTimeout> | null = null;
	function schedulePoll() {
		if (timer) clearTimeout(timer);
		timer = null;
		if (anyRendering.value || activeRun.value) timer = setTimeout(() => void refresh(), 700);
	}

	function confirmLeave(): boolean {
		return !dirty.value || confirm('Discard unsaved changes to this template?');
	}

	function show(v: PidView) {
		if (v.kind !== 'template' && !confirmLeave()) return false;
		view.value = v;
		message.value = null;
		error.value = null;
		if (v.kind === 'drawing') lastPage.value = { id: v.id, page: v.page };
		return true;
	}

	// -- drawings --------------------------------------------------------------

	async function upload(file: Blob, filename: string, drawingType = 'PID', blockSet = 'FIR') {
		const q = new URLSearchParams({ filename, drawing_type: drawingType, block_set: blockSet });
		const d = await run(() => apiPostBytes<Drawing>(`/api/pid/drawings?${q}`, file));
		if (d) {
			if (!checked.value.includes(d.id)) checked.value.push(d.id);
			await refresh();
		}
		return d;
	}

	async function editDrawing(d: Drawing, patch: Partial<Pick<Drawing, 'drawing_type' | 'block_set' | 'force_ocr'>>) {
		const body = { drawing_type: d.drawing_type, block_set: d.block_set, force_ocr: d.force_ocr, ...patch };
		if (await run(() => apiPut<Drawing>(`/api/pid/drawings/${d.id}`, body))) await refresh();
	}

	async function removeDrawing(id: string) {
		await run(() => apiDelete(`/api/pid/drawings/${id}`));
		if (view.value.kind === 'drawing' && view.value.id === id) view.value = { kind: 'none' };
		await refresh();
	}

	const pageImages = new Map<string, Promise<ImageBitmap>>();
	function pageImage(id: string, page: number): Promise<ImageBitmap> {
		const key = `${id}/${page}`;
		let p = pageImages.get(key);
		if (!p) {
			p = apiGetBlob(`/api/pid/drawings/${id}/pages/${page}/image.png`).then((b) => createImageBitmap(b));
			p.catch(() => pageImages.delete(key));
			if (pageImages.size > 8) pageImages.delete(pageImages.keys().next().value!);
			pageImages.set(key, p);
		}
		return p;
	}

	function pageResult(id: string, page: number) {
		return apiGet<PageResult | null>(`/api/pid/drawings/${id}/pages/${page}/result`);
	}

	function pageWords(id: string, page: number) {
		return apiGet<import('../lib/pidTypes').Word[]>(`/api/pid/drawings/${id}/pages/${page}/words`);
	}

	async function analysePage(id: string, page: number) {
		const r = await run(() => apiPostJson<PageResult>(`/api/pid/drawings/${id}/pages/${page}/analyse`, {}));
		if (r) await refresh();
		return r;
	}

	function overrides(id: string, page: number) {
		return apiGet<PageOverride[]>(`/api/pid/drawings/${id}/pages/${page}/overrides`);
	}

	async function setOverride(id: string, page: number, ov: PageOverride | { template_id: string; clear: true }) {
		const path = `/api/pid/drawings/${id}/pages/${page}/overrides/${ov.template_id}`;
		return run(() => ('clear' in ov ? apiDelete(path) : apiPut<PageOverride>(path, ov)));
	}

	// -- templates -------------------------------------------------------------

	async function openTemplate(id: string) {
		if (!confirmLeave()) return;
		const t = await run(() => apiGet<Template>(`/api/pid/templates/${id}`));
		if (!t) return;
		templateSaved.value = t;
		templateDraft.value = clone(t);
		view.value = { kind: 'template', id };
	}

	async function templateFromPage(id: string, page: number, rect: number[], desc: string) {
		const t = await run(() => apiPostJson<Template>('/api/pid/templates/from-page', { doc_id: id, page, rect, desc }));
		if (t) {
			await refresh();
			templateSaved.value = null; // skip the unsaved-changes check for the old one
			templateDraft.value = null;
			await openTemplate(t.id);
			message.value = 'Template created. Click the template to place its tag points, then Save.';
		}
		return t;
	}

	async function uploadTemplate(file: Blob, filename: string, drawingType: string, blockSet: string) {
		const q = new URLSearchParams({ filename, drawing_type: drawingType, block_set: blockSet });
		const t = await run(() => apiPostBytes<Template>(`/api/pid/templates/upload?${q}`, file));
		if (t) {
			await refresh();
			await openTemplate(t.id);
		}
	}

	async function saveTemplate() {
		const d = templateDraft.value;
		if (!d) return;
		const t = await run(() => apiPut<Template>(`/api/pid/templates/${d.id}`, d));
		if (t) {
			templateSaved.value = t;
			templateDraft.value = clone(t);
			message.value = 'Saved';
			await refresh();
		}
	}

	function discardTemplate() {
		if (templateSaved.value) templateDraft.value = clone(templateSaved.value);
		fieldErrors.value = {};
	}

	async function deleteTemplate(id: string) {
		await run(() => apiDelete(`/api/pid/templates/${id}`));
		if (view.value.kind === 'template' && view.value.id === id) {
			templateSaved.value = templateDraft.value = null;
			view.value = { kind: 'none' };
		}
		await refresh();
	}

	async function moveTemplate(id: string, index: number) {
		if (await run(() => apiPostJson<Template>(`/api/pid/templates/${id}/move`, { index }))) {
			await refresh();
			if (templateSaved.value?.id === id) {
				const t = templates.value.find((x) => x.id === id);
				if (t) {
					templateSaved.value = { ...templateSaved.value, priority: t.priority };
					if (templateDraft.value) templateDraft.value.priority = t.priority;
				}
			}
		}
	}

	async function testTemplate(doc: string, page: number) {
		const t = templateDraft.value;
		if (!t) return;
		const result = await run(() => apiPostJson<TestResult>(`/api/pid/templates/${t.id}/test`, { doc_id: doc, page, template: t }));
		if (result) {
			test.value = { template: clone(t), doc, page, result };
			view.value = { kind: 'drawing', id: doc, page };
		}
	}

	async function importLibrary(json: unknown) {
		const r = await run(() => apiPostJson<Template[]>('/api/pid/templates/import', json));
		if (r) {
			settings.value = await apiGet<Settings>('/api/pid/settings');
			message.value = `Imported ${r.length} template(s).`;
			await refresh();
		}
	}

	async function exportLibrary(drawingType: string, blockSet: string) {
		const name = `pid-templates-${drawingType}-${blockSet}.json`;
		const body = { drawing_type: drawingType, block_set: blockSet };
		await run(async () => {
			if (runningInTauri) {
				const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
				const path = await saveDialog({ defaultPath: name, filters: [{ name: 'Template library', extensions: ['json'] }] });
				if (!path) return;
				const res = await apiPostJson<{ path: string }>('/api/pid/templates/export', { ...body, path });
				message.value = `Saved ${res.path}`;
			} else {
				const lib = await apiPostJson<unknown>('/api/pid/templates/export', body);
				downloadBlob(new Blob([JSON.stringify(lib, null, 1)], { type: 'application/json' }), name);
				message.value = `Downloaded ${name}`;
			}
		});
	}

	// -- settings --------------------------------------------------------------

	async function saveSettings(s: Settings) {
		const r = await run(() => apiPut<Settings>('/api/pid/settings', s));
		if (r) {
			settings.value = r;
			message.value = 'Saved';
		}
		return r;
	}

	// -- runs ------------------------------------------------------------------

	async function startRun(docIds: string[]) {
		const r = await run(() => apiPostJson<RunInfo>('/api/pid/runs', { doc_ids: docIds }));
		if (r) {
			view.value = { kind: 'run', id: r.id };
			await refresh();
		}
	}

	async function cancelRun(id: string) {
		await run(() => apiPostJson<RunInfo>(`/api/pid/runs/${id}/cancel`, {}));
		await refresh();
	}

	async function deleteRun(id: string) {
		await run(() => apiDelete(`/api/pid/runs/${id}`));
		if (view.value.kind === 'run' && view.value.id === id) view.value = { kind: 'none' };
		await refresh();
	}

	function runTags(id: string) {
		return run(() => apiGet<TagsTable>(`/api/pid/runs/${id}/tags`));
	}

	function downloadBlob(blob: Blob, name: string) {
		const url = URL.createObjectURL(blob);
		Object.assign(document.createElement('a'), { href: url, download: name }).click();
		setTimeout(() => URL.revokeObjectURL(url), 10_000);
	}

	async function exportRun(id: string, format: 'csv' | 'xlsx') {
		const name = `P&ID tags.${format}`;
		await run(async () => {
			if (runningInTauri) {
				const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
				const path = await saveDialog({
					defaultPath: name,
					filters: [format === 'csv' ? { name: 'CSV', extensions: ['csv'] } : { name: 'Excel workbook', extensions: ['xlsx'] }],
				});
				if (!path) return;
				const res = await apiPostJson<{ path: string }>(`/api/pid/runs/${id}/export`, { format, path });
				message.value = `Saved ${res.path}`;
			} else {
				downloadBlob(await apiPostJsonForBlob(`/api/pid/runs/${id}/export`, { format }), name);
				message.value = `Downloaded ${name}`;
			}
		});
	}

	/** Create (or reuse) an instrument-list import and add this run's tags as its next revision. */
	async function sendToImport(runId: string, recipeId: string | null, newName: string) {
		return run(async () => {
			let id = recipeId;
			if (!id) id = (await apiPostJson<{ id: string }>('/api/mel/recipes', { name: newName || 'Instrument list', target: 'PIL' })).id;
			await apiPostJson(`/api/mel/recipes/${id}/revisions/pid`, { run_id: runId });
			return id;
		});
	}

	return {
		drawings, templates, libraries, runs, settings, ocr, view, checked, busy, error, fieldErrors, message,
		templateSaved, templateDraft, templateDirty, dirty, test, lastPage, anyRendering, activeRun,
		refresh, show, upload, editDrawing, removeDrawing, pageImage, pageResult, pageWords, analysePage, overrides,
		setOverride, openTemplate, templateFromPage, uploadTemplate, saveTemplate, discardTemplate, deleteTemplate,
		moveTemplate, testTemplate, importLibrary, exportLibrary, saveSettings, startRun, cancelRun, deleteRun, runTags,
		exportRun, sendToImport,
	};
});
