// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { ApiError, apiDelete, apiGet, apiGetBlob, apiPut, apiPutBytes } from '../lib/engine';
import type { EquipmentPackageList, KeyListId, KeyListOverview, LoadTypeForm, LoadTypeList, PlantAreaList } from '../lib/keyListTypes';

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
		await refresh();
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
		saveLoadType, deleteLoadType, attachLoadTypePdf, removeLoadTypePdf, loadTypePdf,
	};
});
