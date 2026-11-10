// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { ApiError, apiGet, apiPut } from '../lib/engine';
import type { KeyListOverview, PlantAreaList } from '../lib/keyListTypes';

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const PLANT_AREAS = '/api/keylists/plant-areas';

/** The project's built-in lists. Each is a saved copy plus the draft being edited. */
export const useKeyLists = defineStore('keylists', () => {
	const overview = ref<KeyListOverview | null>(null);
	const busy = ref(false);
	const error = ref<string | null>(null);
	const fieldErrors = ref<Record<string, string>>({});
	const message = ref<string | null>(null);

	const areasSaved = ref<PlantAreaList | null>(null);
	const areasDraft = ref<PlantAreaList | null>(null);
	const dirty = computed(() => !!areasDraft.value && JSON.stringify(areasDraft.value) !== JSON.stringify(areasSaved.value));

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

	/** Load the list from the engine. Unsaved changes are kept unless `force`. */
	async function loadAreas(force = false) {
		if (dirty.value && !force) return;
		const a = await run(() => apiGet<PlantAreaList>(PLANT_AREAS));
		if (a) { areasSaved.value = a; areasDraft.value = clone(a); }
		await refresh();
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

	function discard() {
		if (areasSaved.value) areasDraft.value = clone(areasSaved.value);
		fieldErrors.value = {};
		error.value = null;
	}

	return { overview, busy, error, fieldErrors, message, areasSaved, areasDraft, dirty, refresh, loadAreas, saveAreas, discard };
});
