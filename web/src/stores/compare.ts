import { defineStore } from 'pinia';
import { ref } from 'vue';
import { apiPostJson } from '../lib/engine';
import type { CompareResult } from '../lib/types';
import { tableWizardStore } from './excelWizard';

export const useOldTable = tableWizardStore('compareA');
export const useNewTable = tableWizardStore('compareB');

export const useCompare = defineStore('compare', () => {
	// Which panel is showing: choose the old table, the new table, or the results.
	const stage = ref<'a' | 'b' | 'result'>('a');
	const options = ref({ ignore_case: true, compare_strike: true });
	const result = ref<CompareResult | null>(null);
	const busy = ref(false);
	const error = ref<string | null>(null);

	async function run() {
		const a = useOldTable();
		const b = useNewTable();
		if (!a.spec || !b.spec) return;
		busy.value = true;
		error.value = null;
		try {
			result.value = await apiPostJson<CompareResult>('/api/excel/compare', {
				a: a.spec, b: b.spec, options: options.value,
			});
			stage.value = 'result';
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err);
		} finally {
			busy.value = false;
		}
	}

	function edit(side: 'a' | 'b') {
		const w = side === 'a' ? useOldTable() : useNewTable();
		if (w.result) w.goTo(3); // back to the key column step
		stage.value = side;
	}

	function reset() {
		useOldTable().reset();
		useNewTable().reset();
		result.value = null;
		error.value = null;
		stage.value = 'a';
	}

	return { stage, options, result, busy, error, run, edit, reset };
});
