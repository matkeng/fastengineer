// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { ApiError, apiDelete, apiGet, apiPostJson, apiPostJsonForBlob, apiPut, exportToPath, runningInTauri } from '../lib/engine';
import type {
	Deliverable, DeliverableDetail, DeliverableForm, DeliverablesOverview, Revision, RevisionInfo,
} from '../lib/deliverableTypes';

const API = '/api/deliverables';
const toForm = (d: Deliverable): DeliverableForm => ({
	id: d.id, type: d.type, name: d.name, doc_number: d.doc_number, doc_title: d.doc_title, source: d.source, generator_id: d.generator_id,
	panel_id: d.panel_id,
	filter_column: d.filter_column, filter_text: d.filter_values.join(', '),
});
const toBody = (f: DeliverableForm) => ({
	type: f.type, name: f.name, doc_number: f.doc_number, doc_title: f.doc_title, source: f.source, generator_id: f.source === 'generator' ? f.generator_id : '',
	panel_id: f.source === 'panel' ? f.panel_id : '',
	filter_column: f.filter_column, filter_values: f.filter_column ? f.filter_text.split(',').map((v) => v.trim()).filter(Boolean) : [],
});

/** Deliverables: the issued lists and their lettered revisions. */
export const useDeliverables = defineStore('deliverables', () => {
	const overview = ref<DeliverablesOverview | null>(null);
	const detail = ref<DeliverableDetail | null>(null);
	const form = ref<DeliverableForm | null>(null); // the selected deliverable's details, as edited
	const shown = ref<Revision | null>(null); // the revision being viewed (null: the current content)
	const busy = ref(false);
	const error = ref<string | null>(null);
	const fieldErrors = ref<Record<string, string>>({});
	const message = ref<string | null>(null);
	const dirty = computed(() => !!form.value && !!detail.value && JSON.stringify(form.value) !== JSON.stringify(toForm(detail.value.deliverable)));

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
		const o = await apiGet<DeliverablesOverview>(API).catch(() => null);
		if (o) overview.value = o;
	}

	/** Open a deliverable (with the rows of its current content). */
	async function open(id: string, keepForm = false) {
		const d = await run(() => apiGet<DeliverableDetail>(`${API}/${id}`, { rows: 'true' }));
		if (!d) return;
		detail.value = d;
		if (!keepForm) form.value = toForm(d.deliverable);
		shown.value = null;
	}

	function close() {
		detail.value = form.value = shown.value = null;
	}

	/** `generatorId` null: the content is generated from the Project Load List. `panelId`: a
	 *  Distribution Panel deliverable, whose content is that panel's schedule. */
	async function create(type: string, name: string, generatorId: string | null, panelId?: string): Promise<boolean> {
		const body = panelId !== undefined ? { type, name, source: 'panel', panel_id: panelId }
			: generatorId === null ? { type, name, source: 'project' } : { type, name, source: 'generator', generator_id: generatorId };
		const d = await run(() => apiPostJson<Deliverable>(API, body));
		if (!d) return false;
		await refresh();
		await open(d.id);
		return true;
	}

	async function save() {
		const f = form.value;
		if (!f) return;
		const d = await run(() => apiPut<Deliverable>(`${API}/${f.id}`, toBody(f)));
		if (d) {
			await refresh();
			await open(d.id);
			message.value = 'Saved';
		}
	}

	function discard() {
		if (detail.value) form.value = toForm(detail.value.deliverable);
		fieldErrors.value = {};
		error.value = null;
	}

	async function remove() {
		const id = detail.value?.deliverable.id;
		if (!id) return;
		if ((await run(() => apiDelete(`${API}/${id}`))) !== undefined) {
			close();
			await refresh();
		}
	}

	async function issue(description: string, buildId: string | null): Promise<RevisionInfo | undefined> {
		const id = detail.value?.deliverable.id;
		if (!id) return undefined;
		const r = await run(() => apiPostJson<RevisionInfo>(`${API}/${id}/revisions`, { description, build_id: buildId }));
		if (r) {
			await refresh();
			await open(id, true);
			message.value = `Rev ${r.letter} issued`;
		}
		return r;
	}

	async function view(rev: RevisionInfo | null) {
		if (!rev) {
			shown.value = null;
			return;
		}
		const r = await run(() => apiGet<Revision>(`${API}/revisions/${rev.id}`));
		if (r) shown.value = r;
	}

	async function amend(rev: RevisionInfo, description: string) {
		const id = detail.value?.deliverable.id;
		const r = await run(() => apiPut<RevisionInfo>(`${API}/revisions/${rev.id}`, { description }));
		if (r && id) await open(id, true);
	}

	async function withdraw(rev: RevisionInfo, reason: string): Promise<boolean> {
		const id = detail.value?.deliverable.id;
		const r = await run(() => apiPostJson<{ letter: string }>(`${API}/revisions/${rev.id}/withdraw`, { reason }));
		if (!r || !id) return false;
		await refresh();
		await open(id, true);
		message.value = `Rev ${r.letter} withdrawn`;
		return true;
	}

	async function exportRevision(rev: RevisionInfo, format: 'xlsx' | 'csv') {
		const url = `${API}/revisions/${rev.id}/export`;
		await run(async () => {
			const { name } = await apiGet<{ name: string }>(`${API}/revisions/${rev.id}/name`, { format });
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

	return {
		overview, detail, form, shown, busy, error, fieldErrors, message, dirty,
		refresh, open, close, create, save, discard, remove, issue, view, amend, withdraw, exportRevision,
	};
});
