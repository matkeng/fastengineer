// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { ApiError, apiDelete, apiGet, apiPostJson, apiPut, apiPutWith } from '../lib/engine';
import type { CellValue, EnumList, RefOverview, RefRow, RefTree, TableDetail } from '../lib/refTypes';

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export const useRefData = defineStore('refdata', () => {
	const overview = ref<RefOverview>({ enums: [], trees: [], tables: [] });
	type Kind = 'enum' | 'tree' | 'table';
	const selected = ref<{ kind: Kind; id: string } | null>(null);
	const busy = ref(false);
	const error = ref<string | null>(null);
	const fieldErrors = ref<Record<string, string>>({});
	const message = ref<string | null>(null);

	// Selected list: saved copy and the draft being edited.
	const enumSaved = ref<EnumList | null>(null);
	const enumDraft = ref<EnumList | null>(null);
	// Selected tree: saved copy and draft (items with a parent item).
	const treeSaved = ref<RefTree | null>(null);
	const treeDraft = ref<RefTree | null>(null);
	// Selected table: definition + rows as saved, and a draft of the name/columns.
	const table = ref<TableDetail | null>(null);
	const tableDraft = ref<TableDetail['table'] | null>(null);
	const allEnums = ref<Record<string, EnumList>>({}); // for the column editor's list picker

	const enumDirty = computed(() => !!enumDraft.value && JSON.stringify(enumDraft.value) !== JSON.stringify(enumSaved.value));
	const tableDirty = computed(() => !!tableDraft.value && JSON.stringify(tableDraft.value) !== JSON.stringify(table.value?.table));
	const treeDirty = computed(() => !!treeDraft.value && JSON.stringify(treeDraft.value) !== JSON.stringify(treeSaved.value));
	const dirty = computed(() => enumDirty.value || treeDirty.value || tableDirty.value);

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

	function clearEditors() {
		enumSaved.value = enumDraft.value = null;
		treeSaved.value = treeDraft.value = null;
		table.value = tableDraft.value = null;
	}

	async function select(kind: Kind, id: string) {
		if (!confirmLeave()) return;
		clearEditors();
		selected.value = { kind, id };
		if (kind === 'enum') {
			const e = await run(() => apiGet<EnumList>(`/api/ref/enums/${id}`));
			if (e) { enumSaved.value = e; enumDraft.value = clone(e); }
		} else if (kind === 'tree') {
			const t = await run(() => apiGet<RefTree>(`/api/ref/trees/${id}`));
			if (t) { treeSaved.value = t; treeDraft.value = clone(t); }
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

	const PATHS: Record<Kind, string> = { enum: '/api/ref/enums', tree: '/api/ref/trees', table: '/api/ref/tables' };

	async function create(kind: Kind, name: string) {
		if (!confirmLeave()) return false;
		const obj = await run(() => apiPostJson<{ id: string }>(PATHS[kind], { name }));
		if (!obj) return false;
		await refresh();
		clearEditors();
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

	async function saveTree() {
		const d = treeDraft.value;
		if (!d) return;
		const t = await run(() => apiPut<RefTree>(`/api/ref/trees/${d.id}`, { name: d.name, description: d.description, nodes: d.nodes }));
		if (t) {
			treeSaved.value = t;
			treeDraft.value = clone(t);
			await refresh();
			message.value = 'Saved';
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
		if (treeSaved.value) treeDraft.value = clone(treeSaved.value);
		if (table.value) tableDraft.value = clone(table.value.table);
		fieldErrors.value = {};
		error.value = null;
	}

	async function remove() {
		const s = selected.value;
		if (!s) return;
		const ok = await run(() => apiDelete(`${PATHS[s.kind]}/${s.id}`));
		if (ok !== undefined) {
			selected.value = null;
			clearEditors();
			await refresh();
		}
	}

	// Rows have no version of their own to read, so the row's last-saved time says which
	// copy this edit was made on; the engine refuses it if a colleague saved the row since.
	const lastSeen = (row?: RefRow): Record<string, string> => (row?.updated_at ? { 'X-Workbench-Base-Time': row.updated_at } : {});

	// Rows are saved straight away (no draft). Returns the saved row, or undefined on errors.
	async function saveRow(rowId: string | null, values: Record<string, CellValue>) {
		const t = table.value;
		if (!t) return undefined;
		const base = `/api/ref/tables/${t.table.id}/rows`;
		const seen = lastSeen(t.rows.find((r) => r.id === rowId));
		const row = await run(() => (rowId ? apiPutWith<RefRow>(`${base}/${rowId}`, { values }, seen) : apiPostJson<RefRow>(base, { values })));
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
		const seen = lastSeen(t.rows.find((r) => r.id === rowId));
		const ok = await run(() => apiDelete(`/api/ref/tables/${t.table.id}/rows/${rowId}`, seen));
		if (ok === undefined) return false;
		t.rows = t.rows.filter((r) => r.id !== rowId);
		void refresh();
		return true;
	}

	return {
		overview, selected, busy, error, fieldErrors, message, enumSaved, enumDraft, treeSaved, treeDraft, table, tableDraft,
		allEnums, enumDirty, treeDirty, tableDirty, dirty, refresh, select, create, saveEnum, saveTree, saveColumns, discard,
		remove, saveRow, deleteRow,
		loadAllEnums,
	};
});
