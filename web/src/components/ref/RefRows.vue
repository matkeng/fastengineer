<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import type { ColumnsConfig } from 'datatables.net';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { type CellValue, type ColumnDef, type RefRow, displayCell } from '../../lib/refTypes';
import { useRefData } from '../../stores/refdata';
import AppModal from '../common/AppModal.vue';

const rd = useRefData();
const host = ref<HTMLDivElement | null>(null);
let table: FilteredTable<RefRow> | null = null;
const cols = computed(() => rd.table!.table.columns); // saved columns (rows follow these)
const enums = computed(() => rd.table!.enums);

const editing = ref<{ id: string | null; values: Record<string, CellValue> } | null>(null);
const formErrors = ref<Record<string, string>>({});

function sortValue(v: CellValue, c: ColumnDef): string | number {
	if (v === null || v === undefined) return '';
	if (c.type === 'decimal' || c.type === 'integer') return Number(v);
	return displayCell(v, c, enums.value).toLowerCase();
}

function build() {
	if (!host.value || !rd.table) return;
	table?.api.destroy();
	const columns: ColumnsConfig[] = cols.value.map((c): ColumnsConfig => ({
		title: escapeHtml(c.name) + (c.required ? ' <span class="req" title="Required">*</span>' : ''),
		data: (row: RefRow) => row.values[c.id] ?? null,
		className: c.type === 'integer' || c.type === 'decimal' ? 'dt-right' : c.type === 'boolean' ? 'center' : '',
		render: (v: CellValue, type: string) => {
			if (type === 'sort' || type === 'type') return sortValue(v, c);
			const text = displayCell(v, c, enums.value);
			if (type !== 'display') return text;
			if (c.type === 'boolean' && v !== null) return v ? '<span class="yes">✓</span>' : '<span class="no">✗</span>';
			return escapeHtml(text);
		},
	}));
	const selects: Record<number, { options: { value: string; label: string }[]; test: (v: string, r: RefRow) => boolean }> = {};
	cols.value.forEach((c, i) => {
		if (c.type === 'enum') {
			const items = enums.value[c.enum_id ?? '']?.items ?? [];
			selects[i] = {
				options: [{ value: '', label: 'All' }, ...items.map((it) => ({ value: it.id, label: it.code })), { value: '__blank', label: '(blank)' }],
				test: (v, r) => v === '' || (v === '__blank' ? r.values[c.id] == null : r.values[c.id] === v),
			};
		} else if (c.type === 'boolean') {
			selects[i] = {
				options: [{ value: '', label: 'All' }, { value: 'y', label: 'Yes' }, { value: 'n', label: 'No' }, { value: 'b', label: '(blank)' }],
				test: (v, r) => v === '' || (v === 'y' ? r.values[c.id] === true : v === 'n' ? r.values[c.id] === false : r.values[c.id] == null),
			};
		}
	});
	table = createFilteredTable<RefRow>(host.value, columns.length, {
		data: rd.table.rows,
		columns,
		order: [[0, 'asc']],
		pageLength: 50,
		lengthMenu: [25, 50, 100, 500],
		layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible' }, filename: rd.table.table.name },
		],
		language: { search: 'Search all:', emptyTable: 'No rows yet. Use "Add row".' },
	}, selects);
}

function open(row: RefRow | null) {
	const values: Record<string, CellValue> = {};
	for (const c of cols.value) values[c.id] = row?.values[c.id] ?? (c.type === 'boolean' ? null : '');
	formErrors.value = {};
	editing.value = { id: row?.id ?? null, values };
}

function onClick(e: MouseEvent) {
	const tr = (e.target as HTMLElement).closest('tbody tr');
	if (!tr || !table) return;
	const row = table.api.row(tr as HTMLTableRowElement).data() as RefRow | undefined;
	if (row) open(row);
}

async function save(addAnother = false) {
	const e = editing.value;
	if (!e) return;
	const saved = await rd.saveRow(e.id, e.values);
	if (!saved) {
		formErrors.value = rd.fieldErrors;
		return;
	}
	build();
	if (addAnother) {
		open(null);
		await nextTick();
		(document.querySelector('dialog.modal[open] input, dialog.modal[open] select') as HTMLElement | null)?.focus();
	} else editing.value = null;
}

function close() {
	editing.value = null;
	formErrors.value = {};
	rd.error = null; // the form showed the details; don't leave a stale summary behind
}

async function remove() {
	const e = editing.value;
	if (!e?.id || !confirm('Delete this row?')) return;
	if (await rd.deleteRow(e.id)) {
		editing.value = null;
		build();
	}
}

watch(() => [host.value, rd.table?.table], build);
onBeforeUnmount(() => table?.api.destroy());
</script>

<template>
	<div class="results mel-grid">
		<div class="row">
			<span class="hint">Click a row to edit or delete it.</span>
			<span class="spacer" />
			<button type="button" @click="open(null)">Add row</button>
		</div>
		<div ref="host" class="result-table ref-rows" @click="onClick" />

		<AppModal :open="!!editing" :title="editing?.id ? 'Edit row' : 'Add row'" @close="close">
			<form v-if="editing" class="form-grid" @submit.prevent="save()">
				<label v-for="c in cols" :key="c.id" class="field">
					<span>{{ c.name }}<span v-if="c.required" class="req"> *</span></span>
					<select v-if="c.type === 'enum'" v-model="editing.values[c.id]" :class="{ invalid: formErrors[c.id] }">
						<option :value="''">—</option>
						<option v-for="it in enums[c.enum_id ?? '']?.items ?? []" :key="it.id" :value="it.id" :title="it.description">
							{{ it.code }} – {{ it.value }}
						</option>
					</select>
					<select v-else-if="c.type === 'boolean'" v-model="editing.values[c.id]" :class="{ invalid: formErrors[c.id] }">
						<option :value="null">—</option>
						<option :value="true">Yes</option>
						<option :value="false">No</option>
					</select>
					<input v-else-if="c.type === 'integer'" v-model="editing.values[c.id]" type="text" inputmode="numeric"
						placeholder="Whole number" :class="{ invalid: formErrors[c.id] }" />
					<input v-else-if="c.type === 'decimal'" v-model="editing.values[c.id]" type="text" inputmode="decimal"
						placeholder="Number" :class="{ invalid: formErrors[c.id] }" />
					<input v-else v-model="editing.values[c.id]" type="text" :class="{ invalid: formErrors[c.id] }" />
					<span v-if="formErrors[c.id]" class="warn small">{{ formErrors[c.id] }}</span>
				</label>
				<button type="submit" hidden />
			</form>
			<template #footer>
				<button v-if="editing?.id" type="button" class="secondary" @click="remove">Delete row</button>
				<span class="spacer" />
				<button type="button" class="secondary" @click="close">Cancel</button>
				<button v-if="!editing?.id" type="button" class="secondary" :disabled="rd.busy" @click="save(true)">Save and add another</button>
				<button type="button" :disabled="rd.busy" @click="save()">Save</button>
			</template>
		</AppModal>
	</div>
</template>
