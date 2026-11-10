<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import HistoryButton from '../audit/HistoryButton.vue';
import { computed, nextTick, onMounted, ref } from 'vue';
import { AREA_TYPES, type PlantArea, nextAreaType, plantAreaMatches, plantAreaProblems } from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import {
	type DropPos, childrenMap, indent, insertNode, isDescendant, moveAmongSiblings, moveNode, outdent, removeSubtree,
	subtreeIds, visibleRows,
} from '../../lib/tree';
import { useKeyLists } from '../../stores/keylists';

const kl = useKeyLists();
const d = computed(() => kl.areasDraft!);
const expanded = ref(new Set<string>());
const filter = ref('');
const host = ref<HTMLDivElement | null>(null);

const rows = computed(() => visibleRows(d.value.nodes, expanded.value, filter.value, plantAreaMatches));
const problems = computed(() => ({ ...plantAreaProblems(d.value.nodes), ...kl.fieldErrors }));
const problemCount = computed(() => Object.keys(problems.value).length);
const FIELDS = ['tag', 'description', 'wbs', 'parent'] as const;
const rowProblems = (id: string) => FIELDS.map((f) => problems.value[`${id}.${f}`]).filter(Boolean).join(' · ');
const depth = computed(() => Math.max(0, ...visibleRows(d.value.nodes, new Set(d.value.nodes.map((n) => n.id))).map((r) => r.depth + 1)));
const parents = computed(() => [...childrenMap(d.value.nodes).keys()].filter((k): k is string => !!k));

function expandAll() {
	expanded.value = new Set(parents.value);
}
function collapseAll() {
	expanded.value = new Set();
}
function toggle(id: string) {
	const s = new Set(expanded.value);
	if (s.has(id)) s.delete(id);
	else s.add(id);
	expanded.value = s;
}
function expand(id: string | null) {
	if (!id || expanded.value.has(id)) return;
	expanded.value = new Set([...expanded.value, id]);
}

// -- editing in place ---------------------------------------------------------------
type Field = 'tag' | 'description' | 'wbs';
let before = '';

async function focusField(id: string, field: Field = 'tag') {
	await nextTick();
	host.value?.querySelector<HTMLInputElement>(`[data-node="${id}"] input[data-field="${field}"]`)?.focus();
}

function onFocus(e: FocusEvent) {
	before = (e.target as HTMLInputElement).value;
}

function onKey(e: KeyboardEvent, n: PlantArea, field: Field) {
	const nodes = d.value.nodes;
	if (e.key === 'Escape') {
		n[field] = before;
		(e.target as HTMLInputElement).blur();
	} else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
		e.preventDefault();
		addSibling(n);
	} else if (e.key === 'Enter' || ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && !e.altKey)) {
		e.preventDefault();
		const i = rows.value.findIndex((r) => r.node.id === n.id);
		const next = rows.value[i + (e.key === 'ArrowUp' ? -1 : 1)];
		if (next) void focusField(next.node.id, field);
	} else if (e.altKey && e.key === 'ArrowRight') {
		e.preventDefault();
		if (indent(nodes, n.id)) { expand(n.parent_id); void focusField(n.id, field); }
	} else if (e.altKey && e.key === 'ArrowLeft') {
		e.preventDefault();
		if (outdent(nodes, n.id)) void focusField(n.id, field);
	} else if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
		e.preventDefault();
		if (moveAmongSiblings(nodes, n.id, e.key === 'ArrowUp' ? -1 : 1)) void focusField(n.id, field);
	}
}

function blank(parent: string | null): PlantArea {
	const above = d.value.nodes.find((n) => n.id === parent);
	return { id: newId(), parent_id: parent, wbs: '', tag: '', description: '', area_type: nextAreaType(above?.area_type) };
}

function addChild(n: PlantArea) {
	const c = blank(n.id);
	insertNode(d.value.nodes, c);
	expand(n.id);
	void focusField(c.id);
}

function addSibling(n: PlantArea) {
	const c = { ...blank(n.parent_id), area_type: n.area_type };
	insertNode(d.value.nodes, c, n.id);
	void focusField(c.id);
}

function addTop() {
	const c = blank(null);
	insertNode(d.value.nodes, c);
	filter.value = '';
	void focusField(c.id);
}

function del(n: PlantArea, childCount: number) {
	const total = subtreeIds(d.value.nodes, n.id).size;
	if (childCount && !confirm(`Delete “${n.tag || n.description || 'this item'}” and the ${total - 1} item(s) under it?`)) return;
	removeSubtree(d.value.nodes, n.id);
}

// -- drag and drop ---------------------------------------------------------------------
const dragId = ref<string | null>(null);
const drop = ref<{ id: string; pos: DropPos } | null>(null);
let expandTimer: ReturnType<typeof setTimeout> | null = null;

function onDragStart(e: DragEvent, n: PlantArea) {
	dragId.value = n.id;
	e.dataTransfer?.setData('text/plain', n.id);
	if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
	const rowEl = (e.target as HTMLElement).closest('.tree-row') as HTMLElement | null;
	if (rowEl && e.dataTransfer) e.dataTransfer.setDragImage(rowEl, 24, 14);
}

function canDrop(targetId: string) {
	return !!dragId.value && dragId.value !== targetId && !isDescendant(d.value.nodes, dragId.value, targetId);
}

function onDragOver(e: DragEvent, n: PlantArea, childCount: number, open: boolean) {
	if (!dragId.value) return;
	if (!canDrop(n.id)) {
		if (e.dataTransfer) e.dataTransfer.dropEffect = 'none';
		drop.value = null;
		return;
	}
	e.preventDefault();
	if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
	const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
	const y = (e.clientY - r.top) / r.height;
	const pos: DropPos = y < 0.25 ? 'before' : y > 0.75 ? 'after' : 'inside';
	if (drop.value?.id !== n.id || drop.value.pos !== pos) {
		drop.value = { id: n.id, pos };
		if (expandTimer) clearTimeout(expandTimer);
		expandTimer = null;
		if (pos === 'inside' && childCount && !open) expandTimer = setTimeout(() => expand(n.id), 600);
	}
}

function onDrop(e: DragEvent) {
	e.preventDefault();
	const t = drop.value;
	const id = dragId.value;
	endDrag();
	if (!t || !id) return;
	if (moveNode(d.value.nodes, id, t.id, t.pos) && t.pos === 'inside') expand(t.id);
}

function onDropTop(e: DragEvent) {
	e.preventDefault();
	const id = dragId.value;
	endDrag();
	if (!id) return;
	const tops = childrenMap(d.value.nodes).get(null) ?? [];
	const last = tops[tops.length - 1];
	if (last && last.id !== id) moveNode(d.value.nodes, id, last.id, 'after');
}

function endDrag() {
	dragId.value = null;
	drop.value = null;
	if (expandTimer) clearTimeout(expandTimer);
	expandTimer = null;
}

onMounted(expandAll);
</script>

<template>
	<section class="card wizard ref-editor tree-editor plant-areas">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Plant Areas</h2>
			<span class="spacer" />
			<span v-if="problemCount" class="warn small">{{ problemCount }} problem(s)</span>
			<span v-if="kl.areasDirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="kl.message" class="saved">✓ {{ kl.message }}</span>
			<HistoryButton entity="plant_areas" record-id="plant-areas" label="Plant Areas" />
			<button type="button" class="secondary" :disabled="!kl.areasDirty || kl.busy" @click="kl.discard()">Discard</button>
			<button type="button" :disabled="!kl.areasDirty || kl.busy || problemCount > 0" @click="kl.saveAreas()">Save</button>
		</div>
		<p v-if="kl.error" class="error">{{ kl.error }}</p>

		<div class="row tree-toolbar">
			<input v-model="filter" type="search" class="tree-filter" placeholder="Filter by tag, description, WBS or type…" aria-label="Filter" />
			<button type="button" class="secondary small" @click="expandAll">Expand all</button>
			<button type="button" class="secondary small" @click="collapseAll">Collapse all</button>
			<span class="hint small">{{ d.nodes.length }} items · {{ depth }} level(s)</span>
		</div>

		<div ref="host" class="tree-grid" role="tree" aria-label="Plant Areas" @dragend="endDrag">
			<div class="tree-head">
				<span>Tag number</span><span>Description</span><span>WBS number</span><span>Area type</span><span />
			</div>
			<div v-for="r in rows" :key="r.node.id" class="tree-row" role="treeitem" :aria-level="r.depth + 1"
				:aria-expanded="r.childCount ? r.expanded : undefined" :data-node="r.node.id"
				:class="{
					dragging: dragId === r.node.id || (dragId && isDescendant(d.nodes, dragId, r.node.id)),
					'drop-before': drop?.id === r.node.id && drop.pos === 'before',
					'drop-after': drop?.id === r.node.id && drop.pos === 'after',
					'drop-inside': drop?.id === r.node.id && drop.pos === 'inside',
					match: r.match,
				}"
				@dragover="onDragOver($event, r.node, r.childCount, r.expanded)" @drop="onDrop">
				<span class="tree-cell tree-code">
					<span v-for="(g, i) in r.guides" :key="i" class="guide" :class="{ line: g }" />
					<span v-if="r.depth" class="elbow" :class="{ last: r.last }" />
					<button v-if="r.childCount && !filter" type="button" class="chev" :class="{ open: r.expanded }"
						:aria-label="r.expanded ? 'Collapse' : 'Expand'" @click="toggle(r.node.id)">▸</button>
					<span v-else class="chev-space" />
					<span class="handle" draggable="true" title="Drag to move (drop on the top or bottom edge of a row to place it before or after, on the middle to put it inside)"
						@dragstart="onDragStart($event, r.node)">⠿</span>
					<input v-model="r.node.tag" data-field="tag" class="cell-input mono" aria-label="Tag number"
						:class="{ invalid: problems[`${r.node.id}.tag`] || problems[`${r.node.id}.parent`] }"
						:title="problems[`${r.node.id}.tag`] ?? problems[`${r.node.id}.parent`] ?? ''"
						@focus="onFocus" @keydown="onKey($event, r.node, 'tag')" />
					<span v-if="r.childCount" class="kids" :title="`${r.childCount} item(s) directly under it`">{{ r.childCount }}</span>
				</span>
				<span class="tree-cell">
					<input v-model="r.node.description" data-field="description" class="cell-input" aria-label="Description"
						:class="{ invalid: problems[`${r.node.id}.description`] }" :title="problems[`${r.node.id}.description`] ?? ''"
						@focus="onFocus" @keydown="onKey($event, r.node, 'description')" />
				</span>
				<span class="tree-cell">
					<input v-model="r.node.wbs" data-field="wbs" class="cell-input mono" aria-label="WBS number"
						:class="{ invalid: problems[`${r.node.id}.wbs`] }" :title="problems[`${r.node.id}.wbs`] ?? ''"
						@focus="onFocus" @keydown="onKey($event, r.node, 'wbs')" />
				</span>
				<span class="tree-cell">
					<select v-model="r.node.area_type" class="cell-input" aria-label="Area type">
						<option v-for="t in AREA_TYPES" :key="t" :value="t">{{ t }}</option>
					</select>
				</span>
				<span class="tree-actions">
					<button type="button" class="icon-btn" title="Add an item inside (child)" @click="addChild(r.node)">+▸</button>
					<button type="button" class="icon-btn" title="Add an item below (sibling, Ctrl+Enter)" @click="addSibling(r.node)">+</button>
					<button type="button" class="icon-btn" title="Move up a level (Alt+←)" :disabled="!r.node.parent_id" @click="outdent(d.nodes, r.node.id)">⇤</button>
					<button type="button" class="icon-btn" title="Move inside the item above (Alt+→)" @click="indent(d.nodes, r.node.id) && expand(r.node.parent_id)">⇥</button>
					<button type="button" class="icon-btn" title="Move up (Alt+↑)" @click="moveAmongSiblings(d.nodes, r.node.id, -1)">↑</button>
					<button type="button" class="icon-btn" title="Move down (Alt+↓)" @click="moveAmongSiblings(d.nodes, r.node.id, 1)">↓</button>
					<button type="button" class="icon-btn danger" title="Delete (with the items under it)" @click="del(r.node, r.childCount)">✕</button>
				</span>
				<span v-if="rowProblems(r.node.id)" class="tree-problem warn small" :style="{ paddingLeft: `${(r.depth + 2) * 18 + 22}px` }">
					{{ rowProblems(r.node.id) }}
				</span>
			</div>
			<div v-if="!d.nodes.length" class="tree-empty hint">No plant areas yet. Add the first one below.</div>
			<div v-else-if="!rows.length" class="tree-empty hint">Nothing matches “{{ filter }}”.</div>
			<div v-if="dragId" class="tree-drop-top" @dragover.prevent @drop="onDropTop">Drop here to move to the top level (at the end)</div>
		</div>

		<div class="nav">
			<button type="button" @click="addTop">Add top-level item</button>
			<span class="hint">Drag ⠿ to move items. Alt+arrows: indent, outdent, move. Tag numbers and descriptions are required and unique in the
				whole list; a WBS number is optional but can't be used twice.</span>
		</div>
	</section>
</template>
