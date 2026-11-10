// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { ref } from 'vue';
import { apiPostJson, apiPostJsonForBlob, exportToPath, runningInTauri } from '../lib/engine';
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

	const exportMessage = ref<string | null>(null);

	function defaultExportName(): string {
		const stem = (n?: string) => (n ?? 'table').replace(/\.[^.]+$/, '');
		const name = `compare ${stem(useOldTable().workbook?.filename)} vs ${stem(useNewTable().workbook?.filename)}.xlsx`;
		return name.replace(/[\\/:*?"<>|]+/g, '_');
	}

	/** Export the comparison to .xlsx: Save As dialog on desktop, a download in a browser. */
	async function exportXlsx(selection: { statuses: string[] | null; columns: number[] | null }) {
		const a = useOldTable();
		const b = useNewTable();
		if (!a.spec || !b.spec) return;
		const body = { a: a.spec, b: b.spec, options: options.value, ...selection };
		exportMessage.value = null;
		error.value = null;
		try {
			if (runningInTauri) {
				const { save } = await import('@tauri-apps/plugin-dialog');
				const path = await save({
					defaultPath: defaultExportName(),
					filters: [{ name: 'Excel workbook', extensions: ['xlsx'] }],
				});
				if (!path) return; // cancelled
				busy.value = true;
				const res = await exportToPath('/api/excel/compare/export', body, path);
				exportMessage.value = `Saved ${res.path}`;
			} else {
				busy.value = true;
				const blob = await apiPostJsonForBlob('/api/excel/compare/export', body);
				const url = URL.createObjectURL(blob);
				const link = Object.assign(document.createElement('a'), { href: url, download: defaultExportName() });
				link.click();
				setTimeout(() => URL.revokeObjectURL(url), 10_000);
				exportMessage.value = `Downloaded ${link.download}`;
			}
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

	return { stage, options, result, busy, error, exportMessage, run, exportXlsx, edit, reset };
});
