<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue';
import { newId, type TreeNode } from '../../lib/refTypes';
import {
	type DropPos, childrenMap, indent, insertNode, isDescendant, moveAmongSiblings, moveNode, outdent, removeSubtree,
	subtreeIds, treeProblems, visibleRows,
} from '../../lib/tree';
import { useRefData } from '../../stores/refdata';

const rd = useRefData();
const d = computed(() => rd.treeDraft!);
const expanded = ref(new Set<string>());
const filter = ref('');
const host = ref<HTMLDivElement | null>(null);

const rows = computed(() => visibleRows(d.value.nodes, expanded.value, filter.value));
const problems = computed(() => ({ ...treeProblems(d.value.nodes), ...rd.fieldErrors }));
const problemCount = computed(() => Object.keys(problems.value).filter((k) => k !== 'name').length);
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
type Field = 'code' | 'value' | 'description';
let before = '';

async function focusField(id: string, field: Field = 'code') {
	await nextTick();
	host.value?.querySelector<HTMLInputElement>(`[data-node="${id}"] input[data-field="${field}"]`)?.focus();
}

function onFocus(e: FocusEvent) {
	before = (e.target as HTMLInputElement).value;
}

function onKey(e: KeyboardEvent, n: TreeNode, field: Field) {
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

function blank(parent: string | null): TreeNode {
	return { id: newId(), parent_id: parent, code: '', value: '', description: '' };
}

function addChild(n: TreeNode) {
	const c = blank(n.id);
	insertNode(d.value.nodes, c);
	expand(n.id);
	void focusField(c.id);
}

function addSibling(n: TreeNode) {
	const c = blank(n.parent_id);
	insertNode(d.value.nodes, c, n.id);
	void focusField(c.id);
}

function addTop() {
	const c = blank(null);
	insertNode(d.value.nodes, c);
	filter.value = '';
	void focusField(c.id);
}

function del(n: TreeNode, childCount: number) {
	const total = subtreeIds(d.value.nodes, n.id).size;
	if (childCount && !confirm(`Delete “${n.value || n.code || 'this item'}” and the ${total - 1} item(s) under it?`)) return;
	removeSubtree(d.value.nodes, n.id);
}

// -- drag and drop ---------------------------------------------------------------------
const dragId = ref<string | null>(null);
const drop = ref<{ id: string; pos: DropPos } | null>(null);
let expandTimer: ReturnType<typeof setTimeout> | null = null;

function onDragStart(e: DragEvent, n: TreeNode) {
	dragId.value = n.id;
	e.dataTransfer?.setData('text/plain', n.id);
	if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
	const rowEl = (e.target as HTMLElement).closest('.tree-row') as HTMLElement | null;
	if (rowEl && e.dataTransfer) e.dataTransfer.setDragImage(rowEl, 24, 14);
}

function canDrop(targetId: string) {
	return !!dragId.value && dragId.value !== targetId && !isDescendant(d.value.nodes, dragId.value, targetId);
}

function onDragOver(e: DragEvent, n: TreeNode, childCount: number, open: boolean) {
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

function remove() {
	if (confirm(`Delete the tree "${rd.treeSaved?.name}"?`)) void rd.remove();
}

onMounted(expandAll);
</script>

<template>
	<section class="card wizard ref-editor tree-editor">
		<div class="mel-head">
			<span class="kind tree">Tree</span>
			<input v-model="d.name" class="name-input" aria-label="Tree name" :class="{ invalid: rd.fieldErrors.name }" />
			<span v-if="rd.fieldErrors.name" class="warn small">{{ rd.fieldErrors.name }}</span>
			<span class="spacer" />
			<span v-if="problemCount" class="warn small">{{ problemCount }} problem(s)</span>
			<span v-if="rd.treeDirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="rd.message" class="saved">✓ {{ rd.message }}</span>
			<button type="button" class="secondary" :disabled="!rd.treeDirty || rd.busy" @click="rd.discard()">Discard</button>
			<button type="button" :disabled="!rd.treeDirty || rd.busy || problemCount > 0" @click="rd.saveTree()">Save</button>
		</div>
		<input v-model="d.description" class="desc-input" placeholder="Description (optional)" aria-label="Tree description" />
		<p v-if="rd.error" class="error">{{ rd.error }}</p>

		<div class="row tree-toolbar">
			<input v-model="filter" type="search" class="tree-filter" placeholder="Filter by code, value or description…" aria-label="Filter" />
			<button type="button" class="secondary small" @click="expandAll">Expand all</button>
			<button type="button" class="secondary small" @click="collapseAll">Collapse all</button>
			<span class="hint small">{{ d.nodes.length }} items · {{ depth }} level(s)</span>
		</div>

		<div ref="host" class="tree-grid" role="tree" :aria-label="d.name" @dragend="endDrag">
			<div class="tree-head">
				<span>Code</span><span>Value</span><span>Description</span><span />
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
					<input v-model="r.node.code" data-field="code" class="cell-input mono" aria-label="Code"
						:class="{ invalid: problems[`${r.node.id}.code`] }" :title="problems[`${r.node.id}.code`] ?? ''"
						@focus="onFocus" @keydown="onKey($event, r.node, 'code')" />
					<span v-if="r.childCount" class="kids" :title="`${r.childCount} item(s) directly under it`">{{ r.childCount }}</span>
				</span>
				<span class="tree-cell">
					<input v-model="r.node.value" data-field="value" class="cell-input" aria-label="Value"
						:class="{ invalid: problems[`${r.node.id}.value`] || problems[`${r.node.id}.parent`] }"
						:title="problems[`${r.node.id}.value`] ?? problems[`${r.node.id}.parent`] ?? ''"
						@focus="onFocus" @keydown="onKey($event, r.node, 'value')" />
				</span>
				<span class="tree-cell">
					<input v-model="r.node.description" data-field="description" class="cell-input" aria-label="Description"
						@focus="onFocus" @keydown="onKey($event, r.node, 'description')" />
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
				<span v-if="problems[`${r.node.id}.code`] || problems[`${r.node.id}.value`] || problems[`${r.node.id}.parent`]" class="tree-problem warn small"
					:style="{ paddingLeft: `${(r.depth + 2) * 18 + 22}px` }">
					{{ [problems[`${r.node.id}.code`], problems[`${r.node.id}.value`], problems[`${r.node.id}.parent`]].filter(Boolean).join(' · ') }}
				</span>
			</div>
			<div v-if="!d.nodes.length" class="tree-empty hint">No items yet. Add the first one below.</div>
			<div v-else-if="!rows.length" class="tree-empty hint">Nothing matches “{{ filter }}”.</div>
			<div v-if="dragId" class="tree-drop-top" @dragover.prevent @drop="onDropTop">Drop here to move to the top level (at the end)</div>
		</div>

		<div class="nav">
			<button type="button" @click="addTop">Add top-level item</button>
			<span class="hint">Drag ⠿ to move items. Alt+arrows: indent, outdent, move. Codes are unique in the tree; values are unique at each level.</span>
			<span class="spacer" />
			<button type="button" class="secondary" @click="remove">Delete tree</button>
		</div>
	</section>
</template>
