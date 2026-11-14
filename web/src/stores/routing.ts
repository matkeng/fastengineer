// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { ApiError, apiGet, apiPostJson, apiPostJsonForBlob, apiPut, exportToPath, runningInTauri } from '../lib/engine';
import { createHistory } from '../lib/history';
import { removeEnd, removeSegment, segmentsAt } from '../lib/routingCanvas';
import type { CableRoute, CableRouting, RoutingView, SegmentLoad, Selection } from '../lib/routingTypes';

const URL_ = '/api/cable-routing';
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

/** Cable Routing: the saved map, the draft being edited, and what the engine works out from the draft. */
export const useRouting = defineStore('routing', () => {
	const view = ref<RoutingView | null>(null);
	const saved = ref<CableRouting | null>(null);
	const draft = ref<CableRouting | null>(null);
	const busy = ref(false);
	const error = ref<string | null>(null);
	const message = ref<string | null>(null);
	const selection = ref<Selection | null>(null);
	const tab = ref<'map' | 'cables' | 'segments' | 'rules'>('map');
	/** The Cables tab's status filter ('' for all). */
	const cableFilter = ref('');
	const history = createHistory<CableRouting>();
	const dirty = computed(() => !!draft.value && JSON.stringify(draft.value) !== JSON.stringify(saved.value));
	const errors = computed(() => view.value?.errors ?? {});
	const cableByKey = computed(() => new Map((view.value?.cables ?? []).map((c): [string, CableRoute] => [String(c.row), c])));
	const loadById = computed(() => new Map((view.value?.segments ?? []).map((s): [string, SegmentLoad] => [s.id, s])));

	async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
		busy.value = true;
		error.value = null;
		message.value = null;
		try {
			return await fn();
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err);
			if (err instanceof ApiError && view.value) view.value = { ...view.value, errors: err.fields };
			return undefined;
		} finally {
			busy.value = false;
		}
	}

	function accept(v: RoutingView) {
		view.value = v;
		saved.value = clone(v.doc);
		draft.value = clone(v.doc);
	}

	async function load() {
		const v = await run(() => apiGet<RoutingView>(URL_));
		if (v) {
			accept(v);
			history.clear();
			selection.value = null;
		}
	}

	async function save() {
		if (!draft.value) return;
		const v = await run(() => apiPut<RoutingView>(URL_, draft.value));
		if (v) {
			accept(v);
			message.value = 'Saved';
		}
	}

	let timer: ReturnType<typeof setTimeout> | undefined;
	/** The routes, ladders and errors of the unsaved edits (the draft is kept). */
	async function check() {
		if (!draft.value) return;
		const sent = JSON.stringify(draft.value);
		const v = await apiPostJson<RoutingView>(`${URL_}/check`, draft.value).catch(() => null);
		if (v && sent === JSON.stringify(draft.value)) view.value = v; // not an answer to older edits
	}
	function checkSoon(ms = 250) {
		clearTimeout(timer);
		timer = setTimeout(() => void check(), ms);
	}

	/** Remember the draft as it is, before a change (a drag remembers once, at its start). */
	function remember() {
		if (draft.value) history.record(clone(draft.value));
	}
	/** Change the draft: one step of undo, and the routes are worked out again. */
	function edit(change: (doc: CableRouting) => void) {
		if (!draft.value) return;
		remember();
		change(draft.value);
		checkSoon();
	}
	function undo() {
		const earlier = draft.value && history.undo(clone(draft.value));
		if (earlier) restore(earlier);
	}
	function redo() {
		const later = draft.value && history.redo(clone(draft.value));
		if (later) restore(later);
	}
	function restore(doc: CableRouting) {
		draft.value = doc;
		const s = selection.value;
		if (s && s.kind !== 'cable' && ![...doc.nodes, ...doc.placements, ...doc.segments].some((x) => x.id === s.id)) selection.value = null;
		checkSoon(0);
	}
	function discard() {
		if (!saved.value) return;
		remember();
		restore(clone(saved.value));
	}

	/** Number the nodes and segments again from 1 (in the draft; not saved). */
	async function renumber() {
		if (!draft.value) return;
		remember();
		const v = await run(() => apiPostJson<RoutingView>(`${URL_}/renumber`, draft.value));
		if (v) {
			view.value = v;
			draft.value = clone(v.doc);
		}
	}

	/** The cables' routes or the segments' ladders, as saved, as a file. */
	async function exportTable(table: 'cables' | 'segments', format: 'xlsx' | 'csv') {
		const file = `${table === 'cables' ? 'Cable Routes' : 'Cable Ladder Segments'}.${format}`;
		await run(async () => {
			if (runningInTauri) {
				const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
				const path = await saveDialog({ defaultPath: file, filters: [format === 'csv' ? { name: 'CSV', extensions: ['csv'] } : { name: 'Excel workbook', extensions: ['xlsx'] }] });
				if (path) message.value = `Saved ${(await exportToPath(`${URL_}/export`, { table, format }, path)).path}`;
			} else {
				const href = URL.createObjectURL(await apiPostJsonForBlob(`${URL_}/export`, { table, format }));
				Object.assign(document.createElement('a'), { href, download: file }).click();
				setTimeout(() => URL.revokeObjectURL(href), 10_000);
				message.value = `Downloaded ${file}`;
			}
		});
	}

	function select(s: Selection | null) {
		if (s?.kind !== 'cable' || s.id !== selection.value?.id) picking.value = null;
		selection.value = s;
	}

	// -- a cable's own route ---------------------------------------------------------------
	/** While set, a click on a node or segment of the map adds it to the selected cable's route. */
	const picking = ref<'via' | 'avoid' | null>(null);
	const selectedCable = computed(() => (selection.value?.kind === 'cable' ? cableByKey.value.get(selection.value.id) ?? null : null));
	function addStop(id: string) {
		const key = selectedCable.value?.key;
		const kind = picking.value;
		if (!key || !kind) return;
		edit((d) => {
			const o = (d.overrides[key] ??= { via: [], avoid: [] });
			if (!o[kind].includes(id)) o[kind].push(id);
		});
	}
	function removeStop(kind: 'via' | 'avoid', id: string) {
		const key = selectedCable.value?.key;
		if (!key) return;
		edit((d) => {
			const o = d.overrides[key];
			if (!o) return;
			o[kind] = o[kind].filter((x) => x !== id);
			if (!o.via.length && !o.avoid.length) delete d.overrides[key];
		});
	}
	function clearRoute() {
		const key = selectedCable.value?.key;
		if (key) edit((d) => void delete d.overrides[key]);
		picking.value = null;
	}

	/** Take the selected node, equipment or segment off the map (a node or equipment: with its segments). */
	function removeSelected() {
		const s = selection.value;
		if (!s || s.kind === 'cable' || !draft.value) return;
		if (s.kind === 'segment') edit((d) => removeSegment(d, s.id));
		else {
			const end = { kind: s.kind, id: s.id };
			const n = segmentsAt(draft.value, end).length;
			if (n && !confirm(`Delete it with the ${n} segment(s) that end on it?`)) return;
			edit((d) => removeEnd(d, end));
		}
		selection.value = null;
	}

	/** Asks the map to put this equipment in the middle of what it shows. */
	const placeRequest = ref<{ tag: string; description: string; source: string | null } | null>(null);
	/** Counts up to ask the inspector to put the cursor in the selected segment's length. */
	const focusLength = ref(0);

	return {
		view, saved, draft, busy, error, message, selection, tab, cableFilter, dirty, errors, cableByKey, loadById,
		canUndo: history.canUndo, canRedo: history.canRedo,
		load, save, check, checkSoon, remember, edit, undo, redo, discard, renumber, exportTable, select,
		picking, selectedCable, addStop, removeStop, clearRoute, removeSelected, placeRequest, focusLength,
	};
});
