// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import {
	ApiError, apiDelete, apiGet, apiGetBlob, apiPostBytes, apiPostJson, apiPostJsonForBlob, apiPut, apiPutBytes, runningInTauri,
} from '../lib/engine';
import type {
	Drawing, Library, LibrarySummary, OcrStatus, PageOverride, PageResult, RunInfo, TagsTable, Template, TestResult, Word,
} from '../lib/symbolTypes';

export type SymView =
	| { kind: 'none' }
	| { kind: 'drawing'; id: string; page: number }
	| { kind: 'template'; id: string }
	| { kind: 'run'; id: string }
	| { kind: 'library'; id: string };

const API = '/api/symbols';
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

async function blobToBase64(b: Blob): Promise<string> {
	const bytes = new Uint8Array(await b.arrayBuffer());
	let s = '';
	for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
	return btoa(s);
}

export const useSymbols = defineStore('symbols', () => {
	const drawings = ref<Drawing[]>([]);
	const templates = ref<Template[]>([]); // all libraries, in priority order
	const libraries = ref<LibrarySummary[]>([]);
	const runs = ref<RunInfo[]>([]);
	const ocr = ref<OcrStatus | null>(null);
	const view = ref<SymView>({ kind: 'none' });
	const libraryId = ref<string>(''); // the library shown in the sidebar (and used for uploads)
	const checked = ref<string[]>([]); // drawings ticked for the next run
	const busy = ref(false);
	const error = ref<string | null>(null);
	const fieldErrors = ref<Record<string, string>>({});
	const message = ref<string | null>(null);
	// Template editor: saved copy, draft, and an unsaved painted mask (PNG)
	const templateSaved = ref<Template | null>(null);
	const templateDraft = ref<Template | null>(null);
	const maskDraft = ref<Blob | null>(null);
	// Library settings editor
	const librarySaved = ref<Library | null>(null);
	const libraryDraft = ref<Library | null>(null);
	// A template test shown on the page viewer
	const test = ref<{ template: Template; doc: string; page: number; result: TestResult } | null>(null);
	// The page last looked at: where "Test" runs
	const lastPage = ref<{ id: string; page: number } | null>(null);

	const templateDirty = computed(
		() => !!templateDraft.value && (!!maskDraft.value || JSON.stringify(templateDraft.value) !== JSON.stringify(templateSaved.value)),
	);
	const libraryDirty = computed(
		() => !!libraryDraft.value && JSON.stringify(libraryDraft.value) !== JSON.stringify(librarySaved.value),
	);
	const dirty = computed(() => templateDirty.value || libraryDirty.value);
	const anyRendering = computed(() => drawings.value.some((d) => d.status === 'rendering'));
	const activeRun = computed(() => runs.value.find((r) => r.status === 'queued' || r.status === 'running') ?? null);
	const library = computed(() => libraries.value.find((l) => l.id === libraryId.value) ?? null);
	const libraryName = (id: string) => libraries.value.find((l) => l.id === id)?.name ?? '(deleted library)';

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
			const [l, d, t, r] = await Promise.all([
				apiGet<LibrarySummary[]>(`${API}/libraries`),
				apiGet<Drawing[]>(`${API}/drawings`),
				apiGet<Template[]>(`${API}/templates`),
				apiGet<RunInfo[]>(`${API}/runs`),
			]);
			libraries.value = l;
			drawings.value = d;
			templates.value = t;
			runs.value = r;
			if (!l.some((x) => x.id === libraryId.value)) libraryId.value = l[0]?.id ?? '';
			checked.value = checked.value.filter((id) => d.some((x) => x.id === id));
			ocr.value ??= await apiGet<OcrStatus>(`${API}/ocr`);
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
		return !dirty.value || confirm('Discard unsaved changes?');
	}

	function clearEditors() {
		templateSaved.value = templateDraft.value = null;
		librarySaved.value = libraryDraft.value = null;
		maskDraft.value = null;
	}

	function show(v: SymView) {
		if (!confirmLeave()) return false;
		clearEditors();
		view.value = v;
		message.value = null;
		error.value = null;
		fieldErrors.value = {};
		if (v.kind === 'drawing') lastPage.value = { id: v.id, page: v.page };
		return true;
	}

	// -- libraries -------------------------------------------------------------

	async function openLibrary(id: string) {
		if (!confirmLeave()) return;
		const l = await run(() => apiGet<Library>(`${API}/libraries/${id}`));
		if (!l) return;
		clearEditors();
		librarySaved.value = l;
		libraryDraft.value = clone(l);
		libraryId.value = id;
		view.value = { kind: 'library', id };
	}

	async function createLibrary(name: string, copyFrom: string | null = null) {
		const l = await run(() => apiPostJson<Library>(`${API}/libraries`, { name, copy_from: copyFrom }));
		if (l) {
			await refresh();
			await openLibrary(l.id);
		}
		return l;
	}

	async function saveLibrary() {
		const d = libraryDraft.value;
		if (!d) return;
		const l = await run(() => apiPut<Library>(`${API}/libraries/${d.id}`, d));
		if (l) {
			librarySaved.value = l;
			libraryDraft.value = clone(l);
			await refresh();
			message.value = 'Saved';
		}
		return l;
	}

	function discardLibrary() {
		if (librarySaved.value) libraryDraft.value = clone(librarySaved.value);
		fieldErrors.value = {};
	}

	async function deleteLibrary(id: string) {
		if ((await run(() => apiDelete(`${API}/libraries/${id}`))) === undefined) return;
		clearEditors();
		view.value = { kind: 'none' };
		await refresh();
	}

	/** Change and save a library right away (e.g. an ignored area drawn on a page). */
	async function patchLibrary(id: string, patch: (l: Library) => void) {
		const l = await run(() => apiGet<Library>(`${API}/libraries/${id}`));
		if (!l) return;
		patch(l);
		const saved = await run(() => apiPut<Library>(`${API}/libraries/${id}`, l));
		if (saved) {
			if (librarySaved.value?.id === id) {
				librarySaved.value = saved;
				libraryDraft.value = clone(saved);
			}
			await refresh();
		}
		return saved;
	}

	async function importLibrary(json: unknown) {
		const l = await run(() => apiPostJson<Library>(`${API}/libraries/import`, json));
		if (l) {
			await refresh();
			libraryId.value = l.id;
			message.value = `Imported the library “${l.name}”.`;
		}
	}

	async function restoreExample() {
		const l = await run(() => apiPostJson<Library>(`${API}/libraries/restore-example`, {}));
		if (l) {
			await refresh();
			libraryId.value = l.id;
			message.value = `Added “${l.name}”.`;
		}
	}

	function downloadBlob(blob: Blob, name: string) {
		const url = URL.createObjectURL(blob);
		Object.assign(document.createElement('a'), { href: url, download: name }).click();
		setTimeout(() => URL.revokeObjectURL(url), 10_000);
	}

	async function saveAs(path: string, body: object, name: string, filter: { name: string; extensions: string[] },
		toBlob: (data: unknown) => Promise<Blob> | Blob) {
		await run(async () => {
			if (runningInTauri) {
				const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
				const target = await saveDialog({ defaultPath: name, filters: [filter] });
				if (!target) return;
				const res = await apiPostJson<{ path: string }>(path, { ...body, path: target });
				message.value = `Saved ${res.path}`;
			} else {
				downloadBlob(await toBlob(await apiPostJson<unknown>(path, body)), name);
				message.value = `Downloaded ${name}`;
			}
		});
	}

	async function exportLibrary(id: string) {
		const name = `${libraryName(id).replace(/[\\/:*?"<>|]+/g, '_')}.symbols.json`;
		await saveAs(`${API}/libraries/${id}/export`, {}, name, { name: 'Symbol library', extensions: ['json'] },
			(data) => new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' }));
	}

	// -- drawings --------------------------------------------------------------

	async function upload(file: Blob, filename: string, libId: string) {
		const q = new URLSearchParams({ filename, library_id: libId });
		const d = await run(() => apiPostBytes<Drawing>(`${API}/drawings?${q}`, file));
		if (d) {
			if (!checked.value.includes(d.id)) checked.value.push(d.id);
			await refresh();
		}
		return d;
	}

	async function editDrawing(d: Drawing, patch: Partial<Pick<Drawing, 'library_id' | 'force_ocr'>>) {
		const body = { library_id: d.library_id, force_ocr: d.force_ocr, ...patch };
		if (await run(() => apiPut<Drawing>(`${API}/drawings/${d.id}`, body))) await refresh();
	}

	async function removeDrawing(id: string) {
		await run(() => apiDelete(`${API}/drawings/${id}`));
		if (view.value.kind === 'drawing' && view.value.id === id) view.value = { kind: 'none' };
		await refresh();
	}

	const pageImages = new Map<string, Promise<ImageBitmap>>();
	function pageImage(id: string, page: number): Promise<ImageBitmap> {
		const key = `${id}/${page}`;
		let p = pageImages.get(key);
		if (!p) {
			p = apiGetBlob(`${API}/drawings/${id}/pages/${page}/image.png`).then((b) => createImageBitmap(b));
			p.catch(() => pageImages.delete(key));
			if (pageImages.size > 8) pageImages.delete(pageImages.keys().next().value!);
			pageImages.set(key, p);
		}
		return p;
	}

	const pageResult = (id: string, page: number) => apiGet<PageResult | null>(`${API}/drawings/${id}/pages/${page}/result`);
	const pageWords = (id: string, page: number) => apiGet<Word[]>(`${API}/drawings/${id}/pages/${page}/words`);
	const overrides = (id: string, page: number) => apiGet<PageOverride[]>(`${API}/drawings/${id}/pages/${page}/overrides`);

	async function analysePage(id: string, page: number) {
		const r = await run(() => apiPostJson<PageResult>(`${API}/drawings/${id}/pages/${page}/analyse`, {}));
		if (r) await refresh();
		return r;
	}

	async function setOverride(id: string, page: number, ov: PageOverride | { template_id: string; clear: true }) {
		const path = `${API}/drawings/${id}/pages/${page}/overrides/${ov.template_id}`;
		return run(() => ('clear' in ov ? apiDelete(path) : apiPut<PageOverride>(path, ov)));
	}

	// -- templates -------------------------------------------------------------

	async function openTemplate(id: string, force = false) {
		if (!force && !confirmLeave()) return;
		const t = await run(() => apiGet<Template>(`${API}/templates/${id}`));
		if (!t) return;
		clearEditors();
		templateSaved.value = t;
		templateDraft.value = clone(t);
		libraryId.value = t.library_id;
		view.value = { kind: 'template', id };
	}

	async function templateFromPage(id: string, page: number, rect: number[], desc: string) {
		const t = await run(() => apiPostJson<Template>(`${API}/templates/from-page`, { doc_id: id, page, rect, desc }));
		if (t) {
			await refresh();
			await openTemplate(t.id, true);
			message.value = 'Template created. Click the template to place its tag points, then Save.';
		}
		return t;
	}

	async function uploadTemplate(file: Blob, filename: string, libId: string) {
		const q = new URLSearchParams({ filename, library_id: libId });
		const t = await run(() => apiPostBytes<Template>(`${API}/templates/upload?${q}`, file));
		if (t) {
			await refresh();
			await openTemplate(t.id, true);
		}
	}

	async function saveTemplate() {
		const d = templateDraft.value;
		if (!d) return;
		const t = await run(async () => {
			if (maskDraft.value) {
				await apiPutBytes<Template>(`${API}/templates/${d.id}/mask`, maskDraft.value);
			}
			return apiPut<Template>(`${API}/templates/${d.id}`, d);
		});
		if (t) {
			maskDraft.value = null;
			templateSaved.value = t;
			templateDraft.value = clone(t);
			await refresh();
			message.value = 'Saved';
		}
	}

	async function clearCustomMask() {
		const d = templateDraft.value;
		if (!d) return;
		const t = await run(() => apiDelete(`${API}/templates/${d.id}/mask`) as Promise<Template>);
		if (t) {
			maskDraft.value = null;
			templateSaved.value = { ...templateSaved.value!, has_custom_mask: false, mask_mode: t.mask_mode };
			templateDraft.value = { ...d, has_custom_mask: false, mask_mode: 'auto' };
		}
	}

	function discardTemplate() {
		if (templateSaved.value) templateDraft.value = clone(templateSaved.value);
		maskDraft.value = null;
		fieldErrors.value = {};
	}

	async function deleteTemplate(id: string) {
		await run(() => apiDelete(`${API}/templates/${id}`));
		if (view.value.kind === 'template' && view.value.id === id) {
			clearEditors();
			view.value = { kind: 'none' };
		}
		await refresh();
	}

	async function moveTemplate(id: string, index: number) {
		if (await run(() => apiPostJson<Template>(`${API}/templates/${id}/move`, { index }))) {
			await refresh();
			const t = templates.value.find((x) => x.id === id);
			if (t && templateSaved.value?.id === id) {
				templateSaved.value = { ...templateSaved.value, priority: t.priority };
				if (templateDraft.value) templateDraft.value.priority = t.priority;
			}
		}
	}

	async function testTemplate(doc: string, page: number) {
		const t = templateDraft.value;
		if (!t) return;
		const body: Record<string, unknown> = { doc_id: doc, page, template: t };
		if (maskDraft.value && t.mask_mode === 'custom') body.mask_png = await blobToBase64(maskDraft.value);
		const result = await run(() => apiPostJson<TestResult>(`${API}/templates/${t.id}/test`, body));
		if (result) {
			test.value = { template: clone(t), doc, page, result };
			view.value = { kind: 'drawing', id: doc, page }; // the editor's draft stays in the store
			lastPage.value = { id: doc, page };
		}
	}

	/** Back from a test to the template being edited, keeping its unsaved changes. */
	function backToTemplate() {
		if (templateDraft.value) view.value = { kind: 'template', id: templateDraft.value.id };
	}

	// -- runs ------------------------------------------------------------------

	async function startRun(docIds: string[]) {
		const r = await run(() => apiPostJson<RunInfo>(`${API}/runs`, { doc_ids: docIds }));
		if (r) {
			show({ kind: 'run', id: r.id });
			await refresh();
		}
	}

	async function cancelRun(id: string) {
		await run(() => apiPostJson<RunInfo>(`${API}/runs/${id}/cancel`, {}));
		await refresh();
	}

	async function deleteRun(id: string) {
		await run(() => apiDelete(`${API}/runs/${id}`));
		if (view.value.kind === 'run' && view.value.id === id) view.value = { kind: 'none' };
		await refresh();
	}

	const runTags = (id: string) => run(() => apiGet<TagsTable>(`${API}/runs/${id}/tags`));

	async function exportRun(id: string, format: 'csv' | 'xlsx') {
		const filter = format === 'csv' ? { name: 'CSV', extensions: ['csv'] } : { name: 'Excel workbook', extensions: ['xlsx'] };
		await run(async () => {
			if (runningInTauri) {
				const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
				const path = await saveDialog({ defaultPath: `Tags.${format}`, filters: [filter] });
				if (!path) return;
				const res = await apiPostJson<{ path: string }>(`${API}/runs/${id}/export`, { format, path });
				message.value = `Saved ${res.path}`;
			} else {
				downloadBlob(await apiPostJsonForBlob(`${API}/runs/${id}/export`, { format }), `Tags.${format}`);
				message.value = `Downloaded Tags.${format}`;
			}
		});
	}

	/** Create (or reuse) a list import and add this run's tags as its next revision. */
	async function sendToImport(runId: string, recipeId: string | null, newName: string, target = 'PIL') {
		return run(async () => {
			let id = recipeId;
			if (!id) id = (await apiPostJson<{ id: string }>('/api/mel/recipes', { name: newName || 'Instrument list', target })).id;
			await apiPostJson(`/api/mel/recipes/${id}/revisions/symbols`, { run_id: runId });
			return id;
		});
	}

	return {
		drawings, templates, libraries, runs, ocr, view, libraryId, library, checked, busy, error, fieldErrors, message,
		templateSaved, templateDraft, maskDraft, templateDirty, librarySaved, libraryDraft, libraryDirty, dirty, test,
		lastPage, anyRendering, activeRun, libraryName,
		refresh, show, openLibrary, createLibrary, saveLibrary, discardLibrary, deleteLibrary, patchLibrary, importLibrary,
		restoreExample, exportLibrary, upload, editDrawing, removeDrawing, pageImage, pageResult, pageWords, analysePage,
		overrides, setOverride, openTemplate, templateFromPage, uploadTemplate, saveTemplate, clearCustomMask,
		discardTemplate, deleteTemplate, moveTemplate, testTemplate, backToTemplate, startRun, cancelRun, deleteRun,
		runTags, exportRun, sendToImport,
	};
});
