// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { ApiError, apiDelete, apiGet, apiGetBlob, apiPut, apiPutBytes, apiPutWith } from '../lib/engine';
import type {
	Allocation, CodeList, EelForm, EelView, CodeListId, CodeRow, EquipmentPackageList, KeyListId, KeyListOverview, LoadListRow, LoadListView, LoadTypeForm, LoadTypeList, PlantAreaList,
} from '../lib/keyListTypes';

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const PLANT_AREAS = '/api/keylists/plant-areas';
const PACKAGES = '/api/keylists/equipment-packages';
const LOAD_TYPES = '/api/keylists/load-types';
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
	const codeLists = ref<Record<CodeListId, CodeList | null>>({ 'equipment-codes': null, 'instrument-codes': null });
	const areasDirty = computed(() => differ(areasDraft.value, areasSaved.value));
	const packagesDirty = computed(() => differ(packagesDraft.value, packagesSaved.value));
	const dirty = computed(() => areasDirty.value || packagesDirty.value);

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
		if (selected.value === 'plant-areas' && areasSaved.value) areasDraft.value = clone(areasSaved.value);
		if (selected.value === 'equipment-packages' && packagesSaved.value) packagesDraft.value = clone(packagesSaved.value);
		fieldErrors.value = {};
		error.value = null;
	}

	return {
		overview, selected, busy, error, fieldErrors, message, areasSaved, areasDraft, packagesSaved, packagesDraft,
		loadTypes, areasDirty, packagesDirty, dirty, refresh, select, load, saveAreas, savePackages, discard,
		saveLoadType, deleteLoadType, attachLoadTypePdf, removeLoadTypePdf, loadTypePdf, loadList, loadLoadList, allocate, codeLists, saveCodeRow, deleteCodeRow, eel, saveEelItem, deleteEelItem,
	};
});
