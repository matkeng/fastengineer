// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref, shallowRef } from 'vue';
import { apiDelete, apiGet, apiPostBytes, apiPostJson } from '../lib/engine';
import type { ColumnsResult, ExtractResult, PreviewResult, WorkbookSummary } from '../lib/types';

export const STEPS = ['Workbook', 'Sheet or table', 'Header row', 'Key column', 'Results'] as const;

// One wizard store per use: a list import's file, and the old/new tables of a comparison.
function setup() {
	const step = ref(0);
	const busy = ref(false);
	const error = ref<string | null>(null);

	const workbook = ref<WorkbookSummary | null>(null);
	const sourceId = ref<string | null>(null);
	const preview = ref<PreviewResult | null>(null);
	const headerRow = ref<number | null>(null);
	const headerRows = ref(1);
	const columns = ref<ColumnsResult | null>(null);
	const keyColumn = ref<number | null>(null);
	const skipBlankKeys = ref(true);
	const result = ref<ExtractResult | null>(null);
	// Kept so another wizard can reuse the same file ("same workbook as the old table").
	const file = shallowRef<{ blob: Blob; name: string } | null>(null);

	const source = computed(() => workbook.value?.sources.find((s) => s.id === sourceId.value) ?? null);
	const base = computed(() => `/api/excel/workbooks/${workbook.value?.id}`);

	const canAdvance = computed(() => {
		switch (step.value) {
			case 0: return !!workbook.value;
			case 1: return !!sourceId.value;
			case 2: return headerRow.value !== null;
			case 3: return keyColumn.value !== null;
			default: return false;
		}
	});

	async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
		busy.value = true;
		error.value = null;
		try {
			return await fn();
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err);
			return undefined;
		} finally {
			busy.value = false;
		}
	}

	function clearFrom(fromStep: number) {
		if (fromStep <= 1) { sourceId.value = null; preview.value = null; }
		if (fromStep <= 2) { headerRow.value = null; headerRows.value = 1; columns.value = null; }
		if (fromStep <= 3) { keyColumn.value = null; }
		result.value = null;
	}

	async function openFile(file_: Blob, filename: string) {
		if (workbook.value) void apiDelete(base.value).catch(() => undefined);
		workbook.value = null;
		clearFrom(1);
		const summary = await run(() =>
			apiPostBytes<WorkbookSummary>(`/api/excel/workbooks?filename=${encodeURIComponent(filename)}`, file_),
		);
		if (!summary) return;
		workbook.value = summary;
		file.value = { blob: file_, name: filename };
		// One source only (e.g. a single sheet): pick it for the user.
		if (summary.sources.length === 1) sourceId.value = summary.sources[0].id;
	}

	function chooseSource(id: string) {
		if (id !== sourceId.value) clearFrom(1);
		sourceId.value = id;
	}

	function chooseHeader(row: number, rows = headerRows.value) {
		if (row !== headerRow.value || rows !== headerRows.value) clearFrom(2);
		headerRow.value = row;
		headerRows.value = rows;
	}

	function chooseKey(index: number) {
		if (index !== keyColumn.value) result.value = null;
		keyColumn.value = index;
	}

	// Load what the next step needs before showing it.
	async function next() {
		if (!canAdvance.value || busy.value) return;
		const target = step.value + 1;
		let ok: unknown = true;
		if (target === 2 && !preview.value) {
			ok = await run(async () => {
				const pv = await apiGet<PreviewResult>(`${base.value}/preview`, { source: sourceId.value!, rows: 80 });
				preview.value = pv;
				if (headerRow.value === null && pv.suggested_header_row !== null) {
					headerRow.value = pv.suggested_header_row;
					headerRows.value = pv.suggested_header_rows;
				}
				return true;
			});
		} else if (target === 3 && !columns.value) {
			ok = await run(async () => {
				const cols = await apiGet<ColumnsResult>(`${base.value}/columns`, {
					source: sourceId.value!, header_row: headerRow.value!, header_rows: headerRows.value,
				});
				columns.value = cols;
				if (keyColumn.value === null) keyColumn.value = cols.suggested_key;
				return true;
			});
		} else if (target === 4 && !result.value) {
			ok = await run(async () => {
				result.value = await apiPostJson<ExtractResult>(`${base.value}/extract`, {
					source: sourceId.value, header_row: headerRow.value, header_rows: headerRows.value,
					key_column: keyColumn.value, skip_blank_keys: skipBlankKeys.value,
				});
				return true;
			});
		}
		if (ok) step.value = target;
	}

	function back() {
		error.value = null;
		if (step.value > 0) step.value -= 1;
	}

	function goTo(i: number) {
		// Only allow jumping back to steps already completed.
		if (i < step.value) { error.value = null; step.value = i; }
	}

	function setSkipBlankKeys(value: boolean) {
		skipBlankKeys.value = value;
		result.value = null;
	}

	/** The choices that define the extracted table, for the compare endpoint. */
	const spec = computed(() =>
		result.value && workbook.value
			? {
					workbook_id: workbook.value.id,
					source: sourceId.value!,
					header_row: headerRow.value!,
					header_rows: headerRows.value,
					key_column: keyColumn.value!,
					skip_blank_keys: skipBlankKeys.value,
				}
			: null,
	);

	function reset() {
		if (workbook.value) void apiDelete(base.value).catch(() => undefined);
		workbook.value = null;
		clearFrom(1);
		step.value = 0;
		error.value = null;
	}

	return {
		step, busy, error, workbook, file, sourceId, source, preview, headerRow, headerRows, columns,
		keyColumn, skipBlankKeys, result, spec, canAdvance,
		openFile, chooseSource, chooseHeader, chooseKey, setSkipBlankKeys, next, back, goTo, reset,
	};
}

const stores = new Map<string, ReturnType<typeof makeStore>>();
const makeStore = (id: string) => defineStore(`tableWizard:${id}`, setup);

export function tableWizardStore(id: string) {
	if (!stores.has(id)) stores.set(id, makeStore(id));
	return stores.get(id)!;
}

export type TableWizard = ReturnType<ReturnType<typeof tableWizardStore>>;

