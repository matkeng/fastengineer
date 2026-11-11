// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Pure helpers for a tree stored as a flat node list with parent ids (sibling order = list order).
import type { TreeNode } from './refTypes';

export type DropPos = 'before' | 'after' | 'inside';

/** What the structural helpers need of an item; trees with other columns reuse them. */
export interface TreeItem { id: string; parent_id: string | null }

export interface VisibleRow<T extends TreeItem = TreeNode> {
	node: T;
	depth: number;
	childCount: number;
	expanded: boolean;
	match: boolean; // matches the filter (when filtering)
	/** For drawing guide lines: whether each ancestor level still has siblings below. */
	guides: boolean[];
	last: boolean;
}

/** parent id (null = top) -> children in order */
export function childrenMap<T extends TreeItem>(nodes: T[]): Map<string | null, T[]> {
	const ids = new Set(nodes.map((n) => n.id));
	const m = new Map<string | null, T[]>();
	for (const n of nodes) {
		const p = n.parent_id && ids.has(n.parent_id) ? n.parent_id : null;
		if (!m.has(p)) m.set(p, []);
		m.get(p)!.push(n);
	}
	return m;
}

export function isDescendant(nodes: TreeItem[], ancestorId: string, id: string | null): boolean {
	const byId = new Map(nodes.map((n) => [n.id, n]));
	let p = id;
	const seen = new Set<string>();
	while (p) {
		if (p === ancestorId) return true;
		if (seen.has(p)) return false;
		seen.add(p);
		p = byId.get(p)?.parent_id ?? null;
	}
	return false;
}

export function subtreeIds(nodes: TreeItem[], id: string): Set<string> {
	const out = new Set<string>([id]);
	const kids = childrenMap(nodes);
	const stack = [id];
	while (stack.length) {
		for (const c of kids.get(stack.pop()!) ?? []) {
			if (!out.has(c.id)) {
				out.add(c.id);
				stack.push(c.id);
			}
		}
	}
	return out;
}

/** Ancestors of a node, nearest first. */
export function ancestors(nodes: TreeItem[], id: string): string[] {
	const byId = new Map(nodes.map((n) => [n.id, n]));
	const out: string[] = [];
	let p = byId.get(id)?.parent_id ?? null;
	while (p && !out.includes(p)) {
		out.push(p);
		p = byId.get(p)?.parent_id ?? null;
	}
	return out;
}

export function matches(n: TreeNode, filter: string): boolean {
	const f = filter.trim().toLowerCase();
	return !f || [n.code, n.value, n.description].some((s) => s.toLowerCase().includes(f));
}
const defaultMatches = matches;

/** Rows to show: depth-first, children of collapsed nodes hidden. With a filter, matches and
 *  their ancestors are shown (expanded). `matches` says which columns the filter looks at. */
export function visibleRows<T extends TreeItem = TreeNode>(nodes: T[], expanded: Set<string>, filter = '',
	matches: (n: T, filter: string) => boolean = defaultMatches as unknown as (n: T, filter: string) => boolean): VisibleRow<T>[] {
	const kids = childrenMap(nodes);
	const filtering = !!filter.trim();
	let keep: Set<string> | null = null;
	if (filtering) {
		keep = new Set();
		for (const n of nodes) {
			if (matches(n, filter)) {
				keep.add(n.id);
				for (const a of ancestors(nodes, n.id)) keep.add(a);
			}
		}
	}
	const out: VisibleRow<T>[] = [];
	const walk = (parent: string | null, depth: number, guides: boolean[]) => {
		const list = (kids.get(parent) ?? []).filter((c) => !keep || keep.has(c.id));
		list.forEach((n, i) => {
			const last = i === list.length - 1;
			const childCount = kids.get(n.id)?.length ?? 0;
			const open = filtering || expanded.has(n.id);
			out.push({ node: n, depth, childCount, expanded: open, match: filtering && matches(n, filter), guides, last });
			if (childCount && open) walk(n.id, depth + 1, [...guides, !last]);
		});
	};
	walk(null, 0, []);
	return out;
}

/** Re-order the flat list depth-first so every parent comes before its children. */
function normalise<T extends TreeItem>(nodes: T[]): T[] {
	const kids = childrenMap(nodes);
	const out: T[] = [];
	const walk = (p: string | null) => {
		for (const c of kids.get(p) ?? []) {
			out.push(c);
			walk(c.id);
		}
	};
	walk(null);
	return out;
}

/** Move a node (with its subtree) before/after a target, or inside it as the last child.
 *  Returns false (and changes nothing) for an impossible move. */
export function moveNode(nodes: TreeItem[], id: string, targetId: string, pos: DropPos): boolean {
	if (id === targetId || isDescendant(nodes, id, targetId)) return false;
	const node = nodes.find((n) => n.id === id);
	const target = nodes.find((n) => n.id === targetId);
	if (!node || !target) return false;
	const moving = subtreeIds(nodes, id);
	const block = nodes.filter((n) => moving.has(n.id));
	const rest = nodes.filter((n) => !moving.has(n.id));
	node.parent_id = pos === 'inside' ? target.id : target.parent_id;
	let at: number;
	if (pos === 'before') {
		at = rest.indexOf(target);
	} else {
		// after the target's whole subtree
		const tSub = subtreeIds(rest, target.id);
		at = Math.max(...rest.map((n, i) => (tSub.has(n.id) ? i : -1))) + 1;
	}
	rest.splice(at, 0, ...block);
	nodes.splice(0, nodes.length, ...normalise(rest));
	return true;
}

/** Make a node the last child of its previous sibling. */
export function indent(nodes: TreeItem[], id: string): boolean {
	const n = nodes.find((x) => x.id === id);
	if (!n) return false;
	const sibs = childrenMap(nodes).get(n.parent_id) ?? [];
	const i = sibs.findIndex((s) => s.id === id);
	if (i <= 0) return false;
	return moveNode(nodes, id, sibs[i - 1].id, 'inside');
}

/** Move a node up a level, just after its parent. */
export function outdent(nodes: TreeItem[], id: string): boolean {
	const n = nodes.find((x) => x.id === id);
	if (!n?.parent_id) return false;
	return moveNode(nodes, id, n.parent_id, 'after');
}

/** Swap with the previous (-1) or next (+1) sibling. */
export function moveAmongSiblings(nodes: TreeItem[], id: string, by: -1 | 1): boolean {
	const n = nodes.find((x) => x.id === id);
	if (!n) return false;
	const sibs = childrenMap(nodes).get(n.parent_id) ?? [];
	const i = sibs.findIndex((s) => s.id === id);
	const j = i + by;
	if (j < 0 || j >= sibs.length) return false;
	return moveNode(nodes, id, sibs[j].id, by < 0 ? 'before' : 'after');
}

export function removeSubtree(nodes: TreeItem[], id: string): void {
	const gone = subtreeIds(nodes, id);
	nodes.splice(0, nodes.length, ...nodes.filter((n) => !gone.has(n.id)));
}

/** Insert a new node as the last child of `parentId` (null = top level), or right after `afterId`. */
export function insertNode<T extends TreeItem>(nodes: T[], node: T, afterId?: string): void {
	if (afterId) {
		const sub = subtreeIds(nodes, afterId);
		const at = Math.max(...nodes.map((n, i) => (sub.has(n.id) ? i : -1))) + 1;
		nodes.splice(at, 0, node);
	} else if (node.parent_id) {
		const sub = subtreeIds(nodes, node.parent_id);
		const at = Math.max(...nodes.map((n, i) => (sub.has(n.id) ? i : -1))) + 1;
		nodes.splice(at, 0, node);
	} else {
		nodes.push(node);
	}
}

/** The same rules as the engine's check_tree, for live feedback: field key -> message. */
export function treeProblems(nodes: TreeNode[]): Record<string, string> {
	const key = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
	const out: Record<string, string> = {};
	const codes = new Map<string, string>();
	const values = new Map<string, string>();
	for (const n of nodes) {
		const c = key(n.code);
		if (!c) out[`${n.id}.code`] = 'Required';
		else if (codes.has(c)) out[`${n.id}.code`] = 'Duplicate code';
		else codes.set(c, n.id);
		const v = key(n.value);
		const vk = `${n.parent_id ?? ''}\u0000${v}`;
		if (!v) out[`${n.id}.value`] = 'Required';
		else if (values.has(vk)) out[`${n.id}.value`] = 'Already used at this level';
		else values.set(vk, n.id);
	}
	return out;
}
