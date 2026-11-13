<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The PID Symbols list by loop: one row per loop number (natural order) with its tags, function
// codes and the drawings it was found on; its instrument type (suggested from its functions until
// one is chosen here) and a Verified tick. Each change is saved as it is made.
import type { ColumnsConfig } from 'datatables.net';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { escapeHtml } from '../../lib/cells';
import { type FilteredTable, type SelectFilter, TOOLBAR_LAYOUT, createFilteredTable } from '../../lib/dataTable';
import { ApiError, apiGet, apiPut } from '../../lib/engine';

interface Loop {
	loop: string; functions: string[]; tags: string[]; drawings: string[]; detections: number;
	type_id: string | null; type_name: string; type_by: 'user' | 'auto' | null; suggested_id: string | null;
	verified: boolean; verified_by: string; verified_at: string | null;
}
interface LoopsView { loops: Loop[]; types: { id: string; name: string; functions: string[] }[]; without_loop: number }

const emit = defineEmits<{ changed: [] }>();
const host = ref<HTMLDivElement | null>(null);
const view = ref<LoopsView | null>(null);
const error = ref('');
const note = ref('');
const busy = ref(false);
let table: FilteredTable<Loop> | null = null;

async function load() {
	busy.value = true;
	error.value = '';
	try {
		view.value = await apiGet<LoopsView>('/api/pid-symbols/loops');
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	} finally {
		busy.value = false;
	}
}
onMounted(load);
defineExpose({ load });

const list = (xs: string[]) => xs.map((x) => escapeHtml(x)).join('<br>');
function typeSelect(l: Loop, i: number): string {
	const v = view.value!;
	const sug = v.types.find((t) => t.id === l.suggested_id);
	const opts = [`<option value="__auto__"${l.type_by !== 'user' ? ' selected' : ''}>${sug ? `Suggested: ${escapeHtml(sug.name)}` : '— no match —'}</option>`,
		`<option value=""${l.type_by === 'user' && !l.type_id ? ' selected' : ''}>— none —</option>`,
		...v.types.map((t) => `<option value="${escapeHtml(t.id)}"${l.type_by === 'user' && l.type_id === t.id ? ' selected' : ''}>${escapeHtml(t.name)}${t.functions.length ? ` (${escapeHtml(t.functions.join(', '))})` : ''}</option>`)];
	return `<select class="alloc${l.type_by === 'auto' ? ' auto' : ''}" data-loop="${i}" data-kind="type" aria-label="Instrument type of loop ${escapeHtml(l.loop)}"`
		+ ` title="${l.type_by === 'auto' ? 'Suggested from the loop\'s function codes: choose to confirm or change' : 'Chosen'}">${opts.join('')}</select>`;
}

function build() {
	if (!host.value || !view.value) return;
	table?.api.destroy();
	const v = view.value;
	const rows = v.loops;
	const columns: ColumnsConfig[] = [
		{ title: 'Loop', data: 'loop', className: 'key-col', render: (x: string, t: string) => (t === 'display' ? escapeHtml(x) : x) },
		{ title: 'Function tags', data: (l: Loop) => l.tags.join(' '), render: (x: string, t: string, l: Loop) => (t === 'display' ? list(l.tags) : x) },
		{ title: 'Functions', data: (l: Loop) => l.functions.join(', '), render: (x: string, t: string) => (t === 'display' ? `<code>${escapeHtml(x)}</code>` : x) },
		{ title: 'Drawings', data: (l: Loop) => l.drawings.join('; '), render: (x: string, t: string, l: Loop) => (t === 'display' ? list(l.drawings) : x) },
		{ title: 'Detections', data: 'detections', className: 'dt-right' },
		{
			title: 'Instrument type', data: (l: Loop) => l.type_name, className: 'alloc-col',
			render: (x: string, t: string, l: Loop) => (t === 'display' ? typeSelect(l, rows.indexOf(l)) : x),
		},
		{
			title: 'Verified', data: (l: Loop) => (l.verified ? 'Yes' : 'No'), className: 'center',
			render: (x: string, t: string, l: Loop) => (t !== 'display' ? x
				: `<input type="checkbox" data-loop="${rows.indexOf(l)}" data-kind="verified" aria-label="Loop ${escapeHtml(l.loop)} verified"${l.verified ? ' checked' : ''}`
					+ ` title="${l.verified ? escapeHtml(`Verified by ${l.verified_by}${l.verified_at ? ` on ${new Date(l.verified_at).toLocaleString()}` : ''}`) : 'Tick when checked'}" />`),
		},
	];
	const typeNames = [...new Set(rows.map((l) => l.type_name || '(none)'))].sort();
	const selects: Record<number, SelectFilter<Loop>> = {
		5: { options: [{ value: '', label: 'All' }, { value: '__auto__', label: 'Suggested (not chosen)' }, ...typeNames.map((n) => ({ value: n, label: n }))],
			test: (val, l) => val === '' || (val === '__auto__' ? l.type_by !== 'user' : (l.type_name || '(none)') === val) },
		6: { options: [{ value: '', label: 'All' }, { value: 'y', label: 'Verified' }, { value: 'n', label: 'Not verified' }],
			test: (val, l) => val === '' || l.verified === (val === 'y') },
	};
	table = createFilteredTable<Loop>(host.value, columns.length, {
		data: rows, columns, order: [], pageLength: 50, lengthMenu: [25, 50, 100, 500], layout: TOOLBAR_LAYOUT,
		buttons: [
			{ extend: 'colvis', text: 'Columns' },
			{ extend: 'copyHtml5', text: 'Copy', exportOptions: { columns: ':visible', orthogonal: 'export' } },
			{ extend: 'csvHtml5', text: 'CSV', exportOptions: { columns: ':visible', orthogonal: 'export' }, filename: 'PID Symbols loops' },
		],
		language: { search: 'Search all:', emptyTable: 'No loops: the PID Symbols have no loop numbers (map a loop column in their List Import).' },
	}, selects);
}
watch([view, host], build);
onBeforeUnmount(() => table?.api.destroy());

async function onChange(e: Event) {
	const el = e.target as HTMLInputElement | HTMLSelectElement;
	const kind = el.dataset.kind;
	if (!kind || !view.value) return;
	const l = view.value.loops[Number(el.dataset.loop)];
	if (!l) return;
	const body = kind === 'verified' ? { verified: (el as HTMLInputElement).checked }
		: { type_id: el.value === '__auto__' ? null : el.value };
	error.value = '';
	try {
		const saved = await apiPut<Loop>(`/api/pid-symbols/loops/${encodeURIComponent(l.loop)}`, body);
		Object.assign(l, saved);
		table?.api.rows().invalidate('data').draw(false);
		note.value = kind === 'verified' ? `Loop ${l.loop} ${saved.verified ? 'verified' : 'not verified'}` : `Loop ${l.loop}: ${saved.type_name || 'no type'}`;
		emit('changed');
	} catch (err) {
		error.value = err instanceof ApiError || err instanceof Error ? err.message : String(err);
		table?.api.rows().invalidate('data').draw(false); // show what is saved
	}
}
</script>

<template>
	<div>
		<div class="row">
			<span v-if="view" class="hint small">
				{{ view.loops.length }} loop(s) · {{ view.loops.filter((l) => l.verified).length }} verified ·
				{{ view.loops.filter((l) => l.type_by !== 'user').length }} with a suggested type not yet chosen<template v-if="view.without_loop">
				· {{ view.without_loop }} detection(s) with no loop number are not in any loop</template>
			</span>
			<span class="spacer" />
			<span v-if="note" class="saved">✓ {{ note }}</span>
		</div>
		<p v-if="error" class="error">{{ error }}</p>
		<div class="results mel-grid"><div ref="host" class="result-table" @change="onChange" /></div>
	</div>
</template>
