<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// A spreadsheet-like editable grid: in-cell editing, keyboard navigation, range selection,
// copy / paste as tab-separated text (what Excel puts on the clipboard), and windowed
// rendering so a few thousand rows stay smooth. Cells are shown and edited as text; the
// parent converts edits into its own values.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

export interface GridColumn {
	label: string;
	sub?: string; // second header line (e.g. the <<TAG>>)
	type?: 'text' | 'bool';
	options?: string[]; // suggestions while editing (free text still allowed)
	readonly?: boolean;
	width?: number;
	title?: string;
	badge?: string; // small marker in the header (e.g. "calc")
}

export interface CellEdit {
	r: number;
	c: number;
	value: string;
}

const props = withDefaults(defineProps<{
	columns: GridColumn[];
	cells: string[][]; // display text per row and column
	rowLabels?: string[];
	cellClass?: (r: number, c: number) => string;
	tagSuggestions?: string[]; // offered after typing "<<"
	modifierSuggestions?: string[]; // offered after a "|" inside a tag, e.g. "upper", "left:3"
	canEditRows?: boolean;
	height?: number;
	growColumns?: boolean; // a paste wider than the grid is passed on whole: the parent adds the columns
}>(), { canEditRows: true, height: 0 });

const emit = defineEmits<{
	set: [edits: CellEdit[]];
	insert: [at: number, count: number];
	remove: [rows: number[]];
	focus: [r: number, c: number];
}>();

const ROW_H = 26;
const scroller = ref<HTMLDivElement | null>(null);
const editor = ref<HTMLInputElement | null>(null);
const scrollTop = ref(0);
const viewH = ref(400);
const anchor = ref({ r: 0, c: 0 });
const head = ref({ r: 0, c: 0 });
const editing = ref<{ r: number; c: number; value: string } | null>(null);
const dragging = ref(false);
const listId = `grid-opts-${Math.random().toString(36).slice(2)}`;

const nRows = computed(() => props.cells.length);
const nCols = computed(() => props.columns.length);
const start = computed(() => Math.max(0, Math.floor(scrollTop.value / ROW_H) - 8));
const end = computed(() => Math.min(nRows.value, Math.ceil((scrollTop.value + viewH.value) / ROW_H) + 8));
const visible = computed(() => {
	const out: number[] = [];
	for (let r = start.value; r < end.value; r++) out.push(r);
	return out;
});
const sel = computed(() => ({
	r1: Math.min(anchor.value.r, head.value.r), r2: Math.max(anchor.value.r, head.value.r),
	c1: Math.min(anchor.value.c, head.value.c), c2: Math.max(anchor.value.c, head.value.c),
}));
const inSel = (r: number, c: number) => r >= sel.value.r1 && r <= sel.value.r2 && c >= sel.value.c1 && c <= sel.value.c2;
const isHead = (r: number, c: number) => r === head.value.r && c === head.value.c;
const widths = computed(() => props.columns.map((c) => c.width ?? (c.type === 'bool' ? 70 : 140)));
const rowLabelW = computed(() => Math.max(44, 9 * Math.max(...(props.rowLabels ?? [String(nRows.value)]).map((s) => s.length)) + 16));
const editOptions = computed(() => (editing.value ? props.columns[editing.value.c]?.options ?? [] : []));

// "<<" autocomplete
const tagQuery = ref<string | null>(null);
const tagPick = ref(0);
const tagMatches = computed(() => {
	if (tagQuery.value === null || !props.tagSuggestions?.length) return [];
	const q = tagQuery.value.toLowerCase();
	const bar = tagQuery.value.lastIndexOf('|');
	if (bar >= 0) { // a modifier after the path: <<Tag|up… -> <<Tag|upper>>
		const base = tagQuery.value.slice(0, bar);
		const part = q.slice(bar + 1);
		return (props.modifierSuggestions ?? []).filter((m) => m.toLowerCase().startsWith(part)).map((m) => `<<${base}|${m}>>`).slice(0, 12);
	}
	return props.tagSuggestions.filter((t) => t.toLowerCase().startsWith(`<<${q}`)).slice(0, 12);
});

// the editor sits inside v-for, so a plain template ref would be an array
function setEditor(el: unknown) {
	editor.value = (el as HTMLInputElement | null) ?? null;
}

function measure() {
	if (scroller.value) viewH.value = scroller.value.clientHeight || 400;
}

function onScroll() {
	scrollTop.value = scroller.value?.scrollTop ?? 0;
}

function clamp(r: number, c: number) {
	return { r: Math.max(0, Math.min(nRows.value - 1, r)), c: Math.max(0, Math.min(nCols.value - 1, c)) };
}

function scrollIntoView(r: number) {
	const el = scroller.value;
	if (!el) return;
	const top = r * ROW_H;
	const headerH = 48;
	if (top < el.scrollTop) el.scrollTop = top;
	else if (top + ROW_H > el.scrollTop + el.clientHeight - headerH) el.scrollTop = top + ROW_H - el.clientHeight + headerH;
}

function moveTo(r: number, c: number, extend = false) {
	const p = clamp(r, c);
	head.value = p;
	if (!extend) anchor.value = { ...p };
	scrollIntoView(p.r);
	emit('focus', p.r, p.c);
}

function focusGrid() {
	scroller.value?.focus({ preventScroll: true });
}

function startEdit(initial?: string) {
	const { r, c } = head.value;
	const col = props.columns[c];
	if (!col || col.readonly || r >= nRows.value) return;
	if (col.type === 'bool') {
		toggle(r, c);
		return;
	}
	editing.value = { r, c, value: initial ?? props.cells[r]?.[c] ?? '' };
	tagQuery.value = null;
	void nextTick(() => {
		editor.value?.focus();
		if (initial === undefined) editor.value?.select();
		updateTagQuery();
	});
}

function commit(move: 'down' | 'right' | 'left' | 'none' = 'none') {
	const e = editing.value;
	if (!e) return;
	editing.value = null;
	tagQuery.value = null;
	if (e.value !== (props.cells[e.r]?.[e.c] ?? '')) emit('set', [{ r: e.r, c: e.c, value: e.value }]);
	if (move === 'down') moveTo(e.r + 1, e.c);
	else if (move === 'right') moveTo(e.r, e.c + 1);
	else if (move === 'left') moveTo(e.r, e.c - 1);
	focusGrid();
}

function cancel() {
	editing.value = null;
	tagQuery.value = null;
	focusGrid();
}

function toggle(r: number, c: number) {
	if (props.columns[c]?.readonly) return;
	const on = /^(true|yes|y|1|x|locked)$/i.test(props.cells[r]?.[c] ?? '');
	emit('set', [{ r, c, value: on ? '' : 'TRUE' }]);
}

function clearSelection() {
	const edits: CellEdit[] = [];
	for (let r = sel.value.r1; r <= sel.value.r2; r++)
		for (let c = sel.value.c1; c <= sel.value.c2; c++)
			if (!props.columns[c]?.readonly && (props.cells[r]?.[c] ?? '') !== '') edits.push({ r, c, value: '' });
	if (edits.length) emit('set', edits);
}

function onKey(e: KeyboardEvent) {
	if (editing.value) return;
	const { r, c } = head.value;
	const ctrl = e.ctrlKey || e.metaKey;
	const moves: Record<string, [number, number]> = {
		ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1],
		PageUp: [-Math.floor(viewH.value / ROW_H), 0], PageDown: [Math.floor(viewH.value / ROW_H), 0],
	};
	if (moves[e.key]) {
		e.preventDefault();
		const [dr, dc] = moves[e.key];
		if (ctrl) moveTo(dr ? (dr < 0 ? 0 : nRows.value - 1) : r, dc ? (dc < 0 ? 0 : nCols.value - 1) : c, e.shiftKey);
		else moveTo(r + dr, c + dc, e.shiftKey);
	} else if (e.key === 'Home') {
		e.preventDefault();
		moveTo(ctrl ? 0 : r, 0, e.shiftKey);
	} else if (e.key === 'End') {
		e.preventDefault();
		moveTo(ctrl ? nRows.value - 1 : r, nCols.value - 1, e.shiftKey);
	} else if (e.key === 'Tab') {
		e.preventDefault();
		moveTo(r, c + (e.shiftKey ? -1 : 1));
	} else if (e.key === 'Enter' || e.key === 'F2') {
		e.preventDefault();
		startEdit();
	} else if (e.key === 'Delete' || e.key === 'Backspace') {
		e.preventDefault();
		clearSelection();
	} else if (e.key === ' ' && props.columns[c]?.type === 'bool') {
		e.preventDefault();
		toggle(r, c);
	} else if (ctrl && e.key.toLowerCase() === 'a') {
		e.preventDefault();
		anchor.value = { r: 0, c: 0 };
		head.value = { r: nRows.value - 1, c: nCols.value - 1 };
	} else if (e.key.length === 1 && !ctrl && !e.altKey) {
		e.preventDefault();
		startEdit(e.key);
	}
}

function onEditorKey(e: KeyboardEvent) {
	e.stopPropagation(); // the grid's own key handling must not see keys meant for the editor
	if (tagMatches.value.length) {
		if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
			e.preventDefault();
			const n = tagMatches.value.length;
			tagPick.value = (tagPick.value + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
			return;
		}
		if (e.key === 'Enter' || e.key === 'Tab') {
			e.preventDefault();
			insertTag(tagMatches.value[tagPick.value]);
			return;
		}
		if (e.key === 'Escape') {
			e.preventDefault();
			tagQuery.value = null;
			return;
		}
	}
	if (e.key === 'Enter') {
		e.preventDefault();
		commit('down');
	} else if (e.key === 'Tab') {
		e.preventDefault();
		commit(e.shiftKey ? 'left' : 'right');
	} else if (e.key === 'Escape') {
		e.preventDefault();
		cancel();
	}
}

function updateTagQuery() {
	const el = editor.value;
	if (!el || !props.tagSuggestions?.length) return;
	const before = el.value.slice(0, el.selectionStart ?? el.value.length);
	const m = /<<([^<>]*)$/.exec(before);
	tagQuery.value = m ? m[1] : null;
	tagPick.value = 0;
}

function insertTag(tag: string) {
	const el = editor.value;
	if (!el || !editing.value) return;
	const pos = el.selectionStart ?? el.value.length;
	const before = el.value.slice(0, pos).replace(/<<[^<>]*$/, '');
	const after = el.value.slice(pos).replace(/^[^<>\s]*>>/, '');
	editing.value.value = before + tag + after;
	tagQuery.value = null;
	void nextTick(() => {
		const p = before.length + tag.length;
		el.setSelectionRange(p, p);
		el.focus();
	});
}

// -- mouse -------------------------------------------------------------------

function cellDown(e: MouseEvent, r: number, c: number) {
	if (editing.value && (editing.value.r !== r || editing.value.c !== c)) commit();
	if (editing.value) return;
	e.preventDefault();
	focusGrid();
	if (props.columns[c]?.type === 'bool' && (e.target as HTMLElement).tagName === 'INPUT') {
		moveTo(r, c);
		toggle(r, c);
		return;
	}
	moveTo(r, c, e.shiftKey);
	dragging.value = true;
}

function cellOver(r: number, c: number) {
	if (dragging.value) head.value = { r, c };
}

function rowDown(e: MouseEvent, r: number) {
	if (editing.value) commit();
	e.preventDefault();
	focusGrid();
	if (e.shiftKey) {
		head.value = { r, c: nCols.value - 1 };
		anchor.value = { r: anchor.value.r, c: 0 };
	} else {
		anchor.value = { r, c: 0 };
		head.value = { r, c: nCols.value - 1 };
	}
	emit('focus', r, 0);
}

function stopDrag() {
	dragging.value = false;
}

// -- clipboard ------------------------------------------------------------------

/** Parse Excel's clipboard text: tabs between cells, newlines between rows, quotes around cells with either. */
function parseTsv(text: string): string[][] {
	const rows: string[][] = [];
	let row: string[] = [];
	let cell = '';
	let q = false;
	const t = text.replace(/\r\n/g, '\n');
	for (let i = 0; i < t.length; i++) {
		const ch = t[i];
		if (q) {
			if (ch === '"' && t[i + 1] === '"') { cell += '"'; i++; }
			else if (ch === '"') q = false;
			else cell += ch;
		} else if (ch === '"' && cell === '') q = true;
		else if (ch === '\t') { row.push(cell); cell = ''; }
		else if (ch === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
		else cell += ch;
	}
	if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
	return rows;
}

function onCopy(e: ClipboardEvent) {
	if (editing.value) return;
	e.preventDefault();
	const lines: string[] = [];
	for (let r = sel.value.r1; r <= sel.value.r2; r++) {
		const vals: string[] = [];
		for (let c = sel.value.c1; c <= sel.value.c2; c++) {
			const v = props.cells[r]?.[c] ?? '';
			vals.push(/[\t\n"]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
		}
		lines.push(vals.join('\t'));
	}
	e.clipboardData?.setData('text/plain', lines.join('\r\n'));
}

function onPaste(e: ClipboardEvent) {
	if (editing.value) return;
	e.preventDefault();
	const text = e.clipboardData?.getData('text/plain') ?? '';
	if (!text) return;
	const data = parseTsv(text);
	const { r1, c1 } = sel.value;
	// A single value pasted over a range fills the range (as Excel does)
	const fill = data.length === 1 && data[0].length === 1 && (sel.value.r2 > r1 || sel.value.c2 > c1);
	const need = fill ? 0 : r1 + data.length - nRows.value;
	if (need > 0 && props.canEditRows) emit('insert', nRows.value, need);
	const edits: CellEdit[] = [];
	if (fill) {
		for (let r = r1; r <= sel.value.r2; r++)
			for (let c = c1; c <= sel.value.c2; c++) if (!props.columns[c]?.readonly) edits.push({ r, c, value: data[0][0] });
	} else {
		data.forEach((vals, i) => vals.forEach((v, j) => {
			const r = r1 + i;
			const c = c1 + j;
			if ((c < nCols.value || props.growColumns) && !props.columns[c]?.readonly && (r < nRows.value || props.canEditRows)) edits.push({ r, c, value: v });
		}));
	}
	void nextTick(() => {
		if (edits.length) emit('set', edits);
		head.value = clamp(r1 + (fill ? sel.value.r2 - r1 : data.length - 1), c1 + (fill ? sel.value.c2 - c1 : Math.max(...data.map((d) => d.length)) - 1));
	});
}

// -- rows -----------------------------------------------------------------------

function selectedRows(): number[] {
	const out: number[] = [];
	for (let r = sel.value.r1; r <= sel.value.r2 && r < nRows.value; r++) out.push(r);
	return out;
}

function addRow() {
	emit('insert', nRows.value, 1);
	void nextTick(() => {
		moveTo(nRows.value - 1, 0);
		focusGrid(); // so typing goes straight into the new row
	});
}

function insertAbove() {
	const at = sel.value.r1;
	emit('insert', at, sel.value.r2 - at + 1);
	void nextTick(() => {
		moveTo(at, head.value.c);
		focusGrid();
	});
}

function removeRows() {
	const rows = selectedRows();
	if (rows.length && confirm(`Delete ${rows.length} row(s)?`)) emit('remove', rows);
	moveTo(Math.min(sel.value.r1, nRows.value - 1 - rows.length), head.value.c);
}

function select(r: number, c = 0) {
	moveTo(r, c);
	focusGrid();
}

defineExpose({ select, addRow });

watch(nRows, (n) => {
	if (head.value.r >= n) moveTo(n - 1, head.value.c);
});

let ro: ResizeObserver | null = null;
onMounted(() => {
	measure();
	ro = new ResizeObserver(measure);
	if (scroller.value) ro.observe(scroller.value);
	window.addEventListener('mouseup', stopDrag);
});
onBeforeUnmount(() => {
	ro?.disconnect();
	window.removeEventListener('mouseup', stopDrag);
});

const boolOn = (v: string | undefined) => /^(true|yes|y|1|x|locked)$/i.test(v ?? '');
</script>

<template>
	<div class="edit-grid" :class="{ fixed: !!height }">
		<div v-if="canEditRows" class="row grid-tools">
			<button type="button" class="secondary small" @click="addRow">+ Row</button>
			<button type="button" class="secondary small" :disabled="!nRows" @click="insertAbove">Insert above</button>
			<button type="button" class="secondary small" :disabled="!nRows" @click="removeRows">Delete rows</button>
			<span class="hint">Type or press Enter to edit · Ctrl+C / Ctrl+V copy and paste with Excel · Delete clears</span>
		</div>
		<div
			ref="scroller"
			class="grid-scroll"
			tabindex="0"
			:style="height ? { height: `${height}px` } : {}"
			@scroll="onScroll"
			@keydown="onKey"
			@copy="onCopy"
			@paste="onPaste"
		>
			<table class="egrid" :style="{ width: `${rowLabelW + widths.reduce((a, b) => a + b, 0)}px` }">
				<colgroup>
					<col :style="{ width: `${rowLabelW}px` }" />
					<col v-for="(w, i) in widths" :key="i" :style="{ width: `${w}px` }" />
				</colgroup>
				<thead>
					<tr>
						<th class="corner" />
						<th v-for="(col, c) in columns" :key="c" :title="col.title ?? col.label" :class="{ ro: col.readonly }">
							<div class="h1">{{ col.label }}<span v-if="col.badge" class="badge">{{ col.badge }}</span></div>
							<div v-if="col.sub !== undefined" class="h2">{{ col.sub }}</div>
						</th>
					</tr>
				</thead>
				<tbody>
					<tr v-if="start > 0" :style="{ height: `${start * ROW_H}px` }" class="spacer-row"><td :colspan="nCols + 1" /></tr>
					<tr v-for="r in visible" :key="r" :style="{ height: `${ROW_H}px` }">
						<th class="rowh" :class="{ on: r >= sel.r1 && r <= sel.r2 }" @mousedown="rowDown($event, r)">{{ rowLabels?.[r] ?? r + 1 }}</th>
						<td
							v-for="(col, c) in columns"
							:key="c"
							:class="[cellClass?.(r, c) ?? '', { sel: inSel(r, c), cur: isHead(r, c), ro: col.readonly, bool: col.type === 'bool' }]"
							:title="cells[r]?.[c] && cells[r][c].length > 18 ? cells[r][c] : undefined"
							@mousedown="cellDown($event, r, c)"
							@mouseover="cellOver(r, c)"
							@dblclick="startEdit()"
						>
							<template v-if="editing && editing.r === r && editing.c === c">
								<input
									:ref="setEditor"
									v-model="editing.value"
									class="cell-editor"
									:list="editOptions.length ? listId : undefined"
									@keydown="onEditorKey"
									@input="updateTagQuery"
									@click="updateTagQuery"
									@blur="commit()"
								/>
								<ul v-if="tagMatches.length" class="tag-pop" @mousedown.prevent>
									<li v-for="(t, i) in tagMatches" :key="t" :class="{ on: i === tagPick }" @click="insertTag(t)">{{ t }}</li>
								</ul>
							</template>
							<input v-else-if="col.type === 'bool'" type="checkbox" :checked="boolOn(cells[r]?.[c])" :disabled="col.readonly" tabindex="-1" />
							<span v-else class="cell-text">{{ cells[r]?.[c] }}</span>
						</td>
					</tr>
					<tr v-if="end < nRows" :style="{ height: `${(nRows - end) * ROW_H}px` }" class="spacer-row"><td :colspan="nCols + 1" /></tr>
				</tbody>
			</table>
			<p v-if="!nRows" class="hint empty">No rows. Use + Row, or paste from Excel.</p>
		</div>
		<datalist :id="listId">
			<option v-for="o in editOptions" :key="o" :value="o" />
		</datalist>
	</div>
</template>
