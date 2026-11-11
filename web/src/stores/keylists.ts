// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import {
	ApiError, apiDelete, apiGet, apiGetBlob, apiPostBytes, apiPostJson, apiPostJsonForBlob, apiPut, apiPutBytes, apiPutWith, exportToPath,
	runningInTauri,
} from '../lib/engine';
import type { Catalogue } from '../lib/genTypes';
import type {
	Allocation, CableTypeForm, CableTypeList, CodeList, EelForm, EelView, PlcImportPreview, PlcList, PlcView, CodeListId, CodeRow, EquipmentPackageList, KeyListId, KeyListOverview, LoadListRow, LoadListView, LoadTypeForm, LoadTypeList, PlantAreaList, TemplateLists,
} from '../lib/keyListTypes';
import type { DistributionPanelList, PanelsView } from '../lib/panelTypes';

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const PLANT_AREAS = '/api/keylists/plant-areas';
const PACKAGES = '/api/keylists/equipment-packages';
const LOAD_TYPES = '/api/keylists/load-types';
const PANELS = '/api/distribution-panels';
const differ = (a: unknown, b: unknown) => !!a && JSON.stringify(a) !== JSON.stringify(b);

/** The project's built-in lists. Each is a saved copy plus the draft being edited. */
export const useKeyLists = defineStore('keylists', () => {
	const overview = ref<KeyListOverview | null>(null);
	const selected = ref<KeyListId>('plant-areas');
	const busy = ref(false);
	const error = ref<string | null>(null);
	const fieldErrors = ref<Record<string, string>>({});
	const message = ref<string | null>(null);

	const areasSaved = ref<PlantAreaList | null>(null);
	const areasDraft = ref<PlantAreaList | null>(null);
	const packagesSaved = ref<EquipmentPackageList | null>(null);
	const packagesDraft = ref<EquipmentPackageList | null>(null);
	// Load types have no draft: a row is saved from its form straight away.
	const loadTypes = ref<LoadTypeList | null>(null);
	// The Load List is built from the imports each time it is opened (it can take a moment).
	const loadList = ref<LoadListView | null>(null);
	// Equipment Codes and Instrument Codes: no draft either; a row is saved from its form.
	// The Electrical Equipment List, with the choices for its references.
	const eel = ref<EelView | null>(null);
	// Cable types: no draft; a row is saved from its form.
	const cableTypes = ref<CableTypeList | null>(null);
	const codeLists = ref<Record<CodeListId, CodeList | null>>({ 'equipment-codes': null, 'instrument-codes': null });
	const areasDirty = computed(() => differ(areasDraft.value, areasSaved.value));
	const packagesDirty = computed(() => differ(packagesDraft.value, packagesSaved.value));
	// The PLC List and the card / rack types: saved copies and drafts, Save / Discard.
	const plcSaved = ref<PlcList | null>(null);
	const plcDraft = ref<PlcList | null>(null);
	const plcView = ref<PlcView | null>(null);
	const catSaved = ref<Catalogue | null>(null);
	const catDraft = ref<Catalogue | null>(null);
	const plcDirty = computed(() => differ(plcDraft.value, plcSaved.value));
	const catDirty = computed(() => differ(catDraft.value, catSaved.value));
	// Distribution Panels: a saved copy and a draft, Save / Discard; the engine works out the schedules.
	const panelsSaved = ref<DistributionPanelList | null>(null);
	const panelsDraft = ref<DistributionPanelList | null>(null);
	const panelsView = ref<PanelsView | null>(null);
	const panelSelected = ref<string | null>(null);
	const panelsDirty = computed(() => differ(panelsDraft.value, panelsSaved.value));
	const dirty = computed(() => areasDirty.value || packagesDirty.value || plcDirty.value || catDirty.value || panelsDirty.value);

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
			overview.value = await apiGet<KeyListOverview>('/api/keylists');
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err);
		}
	}

	/** Show another list. Each list keeps its own draft, so nothing is lost by switching. */
	function select(id: KeyListId) {
		selected.value = id;
		error.value = null;
		fieldErrors.value = {};
		message.value = null;
		if (id === 'load-list') void loadLoadList();
		// its circuits come from the Load List, which may have changed since
		if (id === 'distribution-panels') void (panelsDirty.value ? checkPanels() : loadPanels());
	}

	async function loadLoadList() {
		const v = await run(() => apiGet<LoadListView>('/api/loadlist'));
		if (v) loadList.value = v;
		await refresh();
	}

	/** Give rows a plant area and/or load type. Returns the saved rows, or undefined (error set).
	 *  One row's edit tells the engine which copy it was made on, so a colleague's newer change isn't overwritten. */
	async function allocate(rows: LoadListRow[], change: Allocation): Promise<LoadListRow[] | undefined> {
		const body = { rows: rows.map((r) => ({ recipe_id: r.recipe_id, key: r.key })), ...change };
		const seen: Record<string, string> = rows.length === 1 && rows[0].updated_at ? { 'X-Workbench-Base-Time': rows[0].updated_at } : {};
		const saved = await run(() => apiPutWith<LoadListRow[]>('/api/loadlist/allocations', body, seen));
		if (saved) void refresh();
		return saved;
	}

	/** Load the lists from the engine. A list with unsaved changes is left as it is. */
	async function load() {
		if (!areasDirty.value) {
			const a = await run(() => apiGet<PlantAreaList>(PLANT_AREAS));
			if (a) { areasSaved.value = a; areasDraft.value = clone(a); }
		}
		if (!packagesDirty.value) {
			const p = await run(() => apiGet<EquipmentPackageList>(PACKAGES));
			if (p) { packagesSaved.value = p; packagesDraft.value = clone(p); }
		}
		const l = await run(() => apiGet<LoadTypeList>(LOAD_TYPES));
		if (l) loadTypes.value = l;
		if (!plcDirty.value) await loadPlc();
		if (!panelsDirty.value) await loadPanels();
		const ct = await run(() => apiGet<CableTypeList>('/api/keylists/cable-types'));
		if (ct) cableTypes.value = ct;
		const e = await run(() => apiGet<EelView>('/api/eel'));
		if (e) eel.value = e;
		for (const id of ['equipment-codes', 'instrument-codes'] as const) {
			const c = await run(() => apiGet<CodeList>(`/api/keylists/${id}`));
			if (c) codeLists.value[id] = c;
		}
		if (selected.value === 'load-list') await loadLoadList();
		else await refresh();
	}

	/** Save the whole list of load types with `items`. False (with error/fieldErrors set) if refused. */
	async function putLoadTypes(items: unknown[]): Promise<boolean> {
		const l = await run(() => apiPut<LoadTypeList>(LOAD_TYPES, { items }));
		if (!l) return false;
		loadTypes.value = l;
		await refresh();
		return true;
	}

	/** Add the row, or replace the saved row with the same id. */
	/** The deliverable lists a load type has rows for and the tags (fixed in the engine; fetched once). */
	const templateLists = ref<TemplateLists | null>(null);
	async function loadTemplateLists() {
		if (!templateLists.value) templateLists.value = (await run(() => apiGet<TemplateLists>(`${LOAD_TYPES}/lists`))) ?? null;
	}

	function saveLoadType(row: LoadTypeForm): Promise<boolean> {
		const items: unknown[] = [...(loadTypes.value?.items ?? [])];
		const i = items.findIndex((r) => (r as { id: string }).id === row.id);
		if (i >= 0) items.splice(i, 1, row);
		else items.push(row);
		return putLoadTypes(items);
	}

	function deleteLoadType(id: string): Promise<boolean> {
		return putLoadTypes((loadTypes.value?.items ?? []).filter((r) => r.id !== id));
	}

	/** Attach a PDF to a saved load type (replacing any it had). False (with error set) if refused. */
	async function attachLoadTypePdf(id: string, file: File): Promise<boolean> {
		const l = await run(() => apiPutBytes<LoadTypeList>(`${LOAD_TYPES}/${id}/pdf?filename=${encodeURIComponent(file.name)}`, file));
		if (l) loadTypes.value = l;
		return !!l;
	}

	async function removeLoadTypePdf(id: string): Promise<boolean> {
		const l = await run(() => apiDelete(`${LOAD_TYPES}/${id}/pdf`) as Promise<LoadTypeList>);
		if (l) loadTypes.value = l;
		return !!l;
	}

	/** The PDF of a load type, as a file to show or save. */
	async function loadTypePdf(id: string): Promise<Blob | undefined> {
		const b = await run(() => apiGetBlob(`${LOAD_TYPES}/${id}/pdf`));
		return b && new Blob([b], { type: 'application/pdf' });
	}

	/** Add the row to a code list, or replace the saved row with the same id. False (errors set) if refused. */
	async function saveCodeRow(id: CodeListId, row: CodeRow): Promise<boolean> {
		const items = [...(codeLists.value[id]?.items ?? [])];
		const i = items.findIndex((r) => r.id === row.id);
		if (i >= 0) items.splice(i, 1, row);
		else items.push(row);
		return putCodeList(id, items);
	}

	function deleteCodeRow(id: CodeListId, rowId: string): Promise<boolean> {
		return putCodeList(id, (codeLists.value[id]?.items ?? []).filter((r) => r.id !== rowId));
	}

	async function putCodeList(id: CodeListId, items: CodeRow[]): Promise<boolean> {
		const c = await run(() => apiPut<CodeList>(`/api/keylists/${id}`, { items }));
		if (!c) return false;
		codeLists.value[id] = c;
		await refresh();
		return true;
	}

	/** Add the item to the Electrical Equipment List, or replace the saved item with the same id. */
	function saveEelItem(item: EelForm): Promise<boolean> {
		const items: unknown[] = [...(eel.value?.items ?? [])];
		const i = items.findIndex((r) => (r as { id: string }).id === item.id);
		if (i >= 0) items.splice(i, 1, item);
		else items.push(item);
		return putEel(items);
	}

	function deleteEelItem(id: string): Promise<boolean> {
		return putEel((eel.value?.items ?? []).filter((r) => r.id !== id));
	}

	async function putEel(items: unknown[]): Promise<boolean> {
		const e = await run(() => apiPut<EelView>('/api/eel', { items }));
		if (!e) return false;
		eel.value = e;
		await refresh();
		return true;
	}

	// -- PLC List ------------------------------------------------------------------------

	function setPlc(v: PlcView, keepDraft = false) {
		plcView.value = v;
		plcSaved.value = clone(v.plc);
		if (!keepDraft) plcDraft.value = clone(v.plc);
		else if (plcDraft.value) plcDraft.value.updated_at = v.plc.updated_at; // only real edits count as unsaved
		catSaved.value = clone(v.catalogue);
		if (!catDirty.value || !catDraft.value) catDraft.value = clone(v.catalogue);
	}

	async function loadPlc() {
		const v = await run(() => apiGet<PlcView>('/api/plc'));
		if (v) setPlc(v);
	}

	async function savePlc() {
		if (!plcDraft.value) return;
		const v = await run(() => apiPut<PlcView>('/api/plc', plcDraft.value));
		if (v) {
			setPlc(v);
			await refresh();
			message.value = 'Saved';
		}
	}

	/** Errors, findings and totals for unsaved edits (the draft is kept). */
	async function checkPlc() {
		if (!plcDraft.value) return;
		const v = await apiPostJson<PlcView>('/api/plc/check', plcDraft.value).catch(() => null);
		if (v) plcView.value = { ...v, plc: plcDraft.value };
	}

	async function saveCatalogue() {
		if (!catDraft.value) return;
		const c = await run(() => apiPut<Catalogue>('/api/plc/catalogue', catDraft.value));
		if (c) {
			catSaved.value = clone(c);
			catDraft.value = clone(c);
			message.value = 'Card and rack types saved';
			// The engine renumbers the saved list's IO points for the types: take that saved copy
			// (the draft has been renumbered the same way, so only real edits stay unsaved).
			const v = await apiGet<PlcView>('/api/plc').catch(() => null);
			if (v) setPlc(v, true);
			await checkPlc();
		}
	}

	async function addDefaultTypes() {
		const c = await run(() => apiPostJson<Catalogue>('/api/plc/catalogue/defaults', {}));
		if (c) {
			catSaved.value = clone(c);
			catDraft.value = clone(c);
		}
	}

	async function exportPlc() {
		message.value = null;
		await run(async () => {
			if (runningInTauri) {
				const { save: saveDialog } = await import('@tauri-apps/plugin-dialog');
				const path = await saveDialog({ defaultPath: 'PLC List.xlsx', filters: [{ name: 'Excel workbook', extensions: ['xlsx'] }] });
				if (!path) return;
				const res = await exportToPath('/api/plc/export', {}, path);
				message.value = `Saved ${res.path}`;
			} else {
				const blob = await apiPostJsonForBlob('/api/plc/export', {});
				const href = URL.createObjectURL(blob);
				Object.assign(document.createElement('a'), { href, download: 'PLC List.xlsx' }).click();
				setTimeout(() => URL.revokeObjectURL(href), 10_000);
				message.value = 'Downloaded PLC List.xlsx';
			}
		});
	}

	/** Read a PLC List workbook: without `apply` a preview; with it the file replaces the list. */
	async function importPlc(file: File, apply: boolean): Promise<PlcImportPreview | undefined> {
		const q = new URLSearchParams({ filename: file.name, apply: String(apply) });
		const pv = await run(() => apiPostBytes<PlcImportPreview>(`/api/plc/import?${q}`, file));
		if (pv?.applied) {
			await loadPlc();
			await refresh();
			message.value = `Imported ${file.name}`;
		}
		return pv;
	}

	// -- Distribution Panels ---------------------------------------------------------------

	function setPanels(v: PanelsView, keepDraft = false) {
		panelsView.value = v;
		if (!keepDraft) {
			panelsSaved.value = clone(v.doc);
			panelsDraft.value = clone(v.doc);
		}
	}

	async function loadPanels() {
		const v = await run(() => apiGet<PanelsView>(PANELS));
		if (v) setPanels(v);
	}

	async function savePanels() {
		if (!panelsDraft.value) return;
		const v = await run(() => apiPut<PanelsView>(PANELS, panelsDraft.value));
		if (v) {
			setPanels(v);
			await refresh();
			message.value = 'Saved';
		}
	}

	/** The schedules, totals and errors of the unsaved edits (the draft is kept). */
	async function checkPanels() {
		if (!panelsDraft.value) return;
		const sent = JSON.stringify(panelsDraft.value);
		const v = await apiPostJson<PanelsView>(`${PANELS}/check`, panelsDraft.value).catch(() => null);
		if (v && sent === JSON.stringify(panelsDraft.value)) panelsView.value = v; // not an answer to older edits
	}

	/** Put a panel's loads that are on no way yet on its free ways (in the draft; not saved). */
	async function placePanelLoads(panelId: string) {
		if (!panelsDraft.value) return;
		const v = await run(() => apiPostJson<PanelsView>(`${PANELS}/place`, { doc: panelsDraft.value, panel_id: panelId }));
		if (v) {
			panelsView.value = v;
			panelsDraft.value = clone(v.doc);
		}
	}

	/** Add the cable type, or replace the saved one with the same id. False (errors set) if refused. */
	function saveCableType(row: CableTypeForm): Promise<boolean> {
		const items: unknown[] = [...(cableTypes.value?.items ?? [])];
		const i = items.findIndex((r) => (r as { id: string }).id === row.id);
		if (i >= 0) items.splice(i, 1, row);
		else items.push(row);
		return putCableTypes(items);
	}

	function deleteCableType(id: string): Promise<boolean> {
		return putCableTypes((cableTypes.value?.items ?? []).filter((r) => r.id !== id));
	}

	async function putCableTypes(items: unknown[]): Promise<boolean> {
		const c = await run(() => apiPut<CableTypeList>('/api/keylists/cable-types', { items }));
		if (!c) return false;
		cableTypes.value = c;
		await refresh();
		return true;
	}

	/** Add back the default cable types that are missing (the rest is kept). Returns how many. */
	async function addDefaultCableTypes(): Promise<number | undefined> {
		const before = cableTypes.value?.items.length ?? 0;
		const c = await run(() => apiPostJson<CableTypeList>('/api/keylists/cable-types/defaults', {}));
		if (!c) return undefined;
		cableTypes.value = c;
		await refresh();
		return c.items.length - before;
	}

	async function saveAreas() {
		const d = areasDraft.value;
		if (!d) return;
		const a = await run(() => apiPut<PlantAreaList>(PLANT_AREAS, { nodes: d.nodes }));
		if (a) {
			areasSaved.value = a;
			areasDraft.value = clone(a);
			await refresh();
			message.value = 'Saved';
		}
	}

	async function savePackages() {
		const d = packagesDraft.value;
		if (!d) return;
		const p = await run(() => apiPut<EquipmentPackageList>(PACKAGES, { items: d.items, types: d.types }));
		if (p) {
			packagesSaved.value = p;
			packagesDraft.value = clone(p);
			await refresh();
			message.value = 'Saved';
		}
	}

	/** Drop the unsaved changes of the list that is showing. */
	function discard() {
		if (selected.value === 'plc' && plcSaved.value) plcDraft.value = clone(plcSaved.value);
		if (selected.value === 'distribution-panels' && panelsSaved.value) panelsDraft.value = clone(panelsSaved.value);
		if (selected.value === 'plant-areas' && areasSaved.value) areasDraft.value = clone(areasSaved.value);
		if (selected.value === 'equipment-packages' && packagesSaved.value) packagesDraft.value = clone(packagesSaved.value);
		fieldErrors.value = {};
		error.value = null;
	}

	return {
		overview, selected, busy, error, fieldErrors, message, areasSaved, areasDraft, packagesSaved, packagesDraft,
		loadTypes, areasDirty, packagesDirty, dirty, refresh, select, load, saveAreas, savePackages, discard,
		saveLoadType, deleteLoadType, templateLists, loadTemplateLists, attachLoadTypePdf, removeLoadTypePdf, loadTypePdf, loadList, loadLoadList, allocate, codeLists, saveCodeRow, deleteCodeRow, eel, saveEelItem, deleteEelItem, cableTypes, saveCableType, deleteCableType, addDefaultCableTypes,
		plcSaved, plcDraft, plcView, catSaved, catDraft, plcDirty, catDirty, loadPlc, savePlc, checkPlc, saveCatalogue,
		addDefaultTypes, exportPlc, importPlc,
		panelsSaved, panelsDraft, panelsView, panelSelected, panelsDirty, loadPanels, savePanels, checkPanels, placePanelLoads,
		discardCatalogue: () => { if (catSaved.value) catDraft.value = clone(catSaved.value); },
	};
});
