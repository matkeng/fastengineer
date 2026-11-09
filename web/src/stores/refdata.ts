// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { ApiError, apiDelete, apiGet, apiPostJson, apiPut } from '../lib/engine';
import type { CellValue, EnumList, RefOverview, RefRow, TableDetail } from '../lib/refTypes';

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export const useRefData = defineStore('refdata', () => {
	const overview = ref<RefOverview>({ enums: [], tables: [] });
	const selected = ref<{ kind: 'enum' | 'table'; id: string } | null>(null);
	const busy = ref(false);
	const error = ref<string | null>(null);
	const fieldErrors = ref<Record<string, string>>({});
	const message = ref<string | null>(null);

	// Selected list: saved copy and the draft being edited.
	const enumSaved = ref<EnumList | null>(null);
	const enumDraft = ref<EnumList | null>(null);
	// Selected table: definition + rows as saved, and a draft of the name/columns.
	const table = ref<TableDetail | null>(null);
	const tableDraft = ref<TableDetail['table'] | null>(null);
	const allEnums = ref<Record<string, EnumList>>({}); // for the column editor's list picker

	const enumDirty = computed(() => !!enumDraft.value && JSON.stringify(enumDraft.value) !== JSON.stringify(enumSaved.value));
	const tableDirty = computed(() => !!tableDraft.value && JSON.stringify(tableDraft.value) !== JSON.stringify(table.value?.table));
	const dirty = computed(() => enumDirty.value || tableDirty.value);

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

	/** Reload the sidebar. Doesn't touch the editor's message or errors. */
	async function refresh() {
		try {
			overview.value = await apiGet<RefOverview>('/api/ref');
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err);
		}
	}

	function confirmLeave(): boolean {
		return !dirty.value || confirm('Discard unsaved changes?');
	}

	async function select(kind: 'enum' | 'table', id: string) {
		if (!confirmLeave()) return;
		enumSaved.value = enumDraft.value = null;
		table.value = tableDraft.value = null;
		selected.value = { kind, id };
		if (kind === 'enum') {
			const e = await run(() => apiGet<EnumList>(`/api/ref/enums/${id}`));
			if (e) { enumSaved.value = e; enumDraft.value = clone(e); }
		} else {
			await loadTable(id);
		}
	}

	async function loadTable(id: string) {
		const d = await run(() => apiGet<TableDetail>(`/api/ref/tables/${id}`));
		if (d) { table.value = d; tableDraft.value = clone(d.table); }
		await loadAllEnums();
	}

	async function loadAllEnums() {
		const out: Record<string, EnumList> = {};
		for (const e of overview.value.enums) {
			const full = await apiGet<EnumList>(`/api/ref/enums/${e.id}`).catch(() => null);
			if (full) out[full.id] = full;
		}
		allEnums.value = out;
	}

	async function create(kind: 'enum' | 'table', name: string) {
		if (!confirmLeave()) return false;
		const obj = await run(() => apiPostJson<{ id: string }>(kind === 'enum' ? '/api/ref/enums' : '/api/ref/tables', { name }));
		if (!obj) return false;
		await refresh();
		enumDraft.value = enumSaved.value = null;
		tableDraft.value = table.value = null;
		await select(kind, obj.id);
		return true;
	}

	async function saveEnum() {
		const d = enumDraft.value;
		if (!d) return;
		const e = await run(() => apiPut<EnumList>(`/api/ref/enums/${d.id}`, { name: d.name, description: d.description, items: d.items }));
		if (e) {
			enumSaved.value = e;
			enumDraft.value = clone(e);
			message.value = 'Saved';
			await refresh();
		}
	}

	async function saveColumns() {
		const d = tableDraft.value;
		if (!d) return;
		const res = await run(() => apiPut<TableDetail>(`/api/ref/tables/${d.id}`, { name: d.name, description: d.description, columns: d.columns }));
		if (res) {
			table.value = res;
			tableDraft.value = clone(res.table);
			message.value = 'Saved';
			await refresh();
		}
	}

	function discard() {
		if (enumSaved.value) enumDraft.value = clone(enumSaved.value);
		if (table.value) tableDraft.value = clone(table.value.table);
		fieldErrors.value = {};
		error.value = null;
	}

	async function remove() {
		const s = selected.value;
		if (!s) return;
		const ok = await run(() => apiDelete(s.kind === 'enum' ? `/api/ref/enums/${s.id}` : `/api/ref/tables/${s.id}`));
		if (ok !== undefined) {
			selected.value = null;
			enumSaved.value = enumDraft.value = null;
			table.value = tableDraft.value = null;
			await refresh();
		}
	}

	// Rows are saved straight away (no draft). Returns the saved row, or undefined on errors.
	async function saveRow(rowId: string | null, values: Record<string, CellValue>) {
		const t = table.value;
		if (!t) return undefined;
		const base = `/api/ref/tables/${t.table.id}/rows`;
		const row = await run(() => (rowId ? apiPut<RefRow>(`${base}/${rowId}`, { values }) : apiPostJson<RefRow>(base, { values })));
		if (row) {
			const i = t.rows.findIndex((r) => r.id === row.id);
			if (i >= 0) t.rows.splice(i, 1, row);
			else t.rows.push(row);
			void refresh();
		}
		return row;
	}

	async function deleteRow(rowId: string) {
		const t = table.value;
		if (!t) return false;
		const ok = await run(() => apiDelete(`/api/ref/tables/${t.table.id}/rows/${rowId}`));
		if (ok === undefined) return false;
		t.rows = t.rows.filter((r) => r.id !== rowId);
		void refresh();
		return true;
	}

	return {
		overview, selected, busy, error, fieldErrors, message, enumSaved, enumDraft, table, tableDraft, allEnums,
		enumDirty, tableDirty, dirty, refresh, select, create, saveEnum, saveColumns, discard, remove, saveRow, deleteRow,
		loadAllEnums,
	};
});
