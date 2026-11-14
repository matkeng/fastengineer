// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// The geometry and the edits of the Cable Routing map (no Vue, no DOM: see routingCanvas.test.ts).
import { newId } from './refTypes';
import { type CableRouting, type End, MAX_NODES, type Placement, type RouteNode, type Segment } from './routingTypes';

export interface Pt { x: number; y: number }
/** screen = world * scale + (ox, oy) */
export interface ViewBox { scale: number; ox: number; oy: number }

export const MIN_SCALE = 0.1;
export const MAX_SCALE = 6;
export const nodeTag = (n: number) => `N${String(n).padStart(3, '0')}`;
export const segmentTag = (n: number) => `S-${String(n).padStart(3, '0')}`;
export const snap = (v: number, grid: number) => (grid > 0 ? Math.round(v / grid) * grid : v);
/** How the engine compares names: ignoring case and extra spaces. */
export const nameKey = (s: string) => s.replace(/\s+/g, ' ').trim().toLowerCase();

function numbers(tags: string[], pattern: RegExp): Set<number> {
	const out = new Set<number>();
	for (const t of tags) {
		const m = pattern.exec(t);
		if (m) out.add(Number(m[1]));
	}
	return out;
}

/** The next number from `start` not in use; past `limit`, the lowest free one. null when all are taken. */
function freeNumber(used: Set<number>, start: number, limit: number | null): number | null {
	let n = Math.max(start, 1);
	while (used.has(n)) n++;
	if (limit === null || n <= limit) return n;
	for (let i = 1; i <= limit; i++) if (!used.has(i)) return i;
	return null;
}

/** A new node with the next tag (numbers are not reused until they run out). null: all 999 are in use. */
export function addNode(doc: CableRouting, x: number, y: number): RouteNode | null {
	const n = freeNumber(numbers(doc.nodes.map((d) => d.tag), /^N(\d{3})$/), doc.next_node, MAX_NODES);
	if (n === null || doc.nodes.length >= MAX_NODES) return null;
	const node: RouteNode = { id: newId(), tag: nodeTag(n), x, y };
	doc.nodes.push(node);
	doc.next_node = n + 1;
	return node;
}

export function addSegment(doc: CableRouting, a: End, b: End, bends: [number, number][] = []): Segment {
	const n = freeNumber(numbers(doc.segments.map((s) => s.tag), /^S-(\d{3,})$/), doc.next_segment, null) ?? 1;
	const seg: Segment = { id: newId(), tag: segmentTag(n), a: { ...a }, b: { ...b }, bends, length_m: null, ladders: {} };
	doc.segments.push(seg);
	doc.next_segment = n + 1;
	return seg;
}

export function addPlacement(doc: CableRouting, tag: string, x: number, y: number, description = '', source: string | null = null): Placement {
	const p: Placement = { id: newId(), tag, description, source, x, y, w: 120, h: 60 };
	doc.placements.push(p);
	return p;
}

export const sameEnd = (a: End, b: End) => a.kind === b.kind && a.id === b.id;

/** The middle of what a segment ends on. */
export function endCentre(doc: CableRouting, end: End): Pt | null {
	if (end.kind === 'node') {
		const n = doc.nodes.find((d) => d.id === end.id);
		return n ? { x: n.x, y: n.y } : null;
	}
	const p = doc.placements.find((d) => d.id === end.id);
	return p ? { x: p.x + p.w / 2, y: p.y + p.h / 2 } : null;
}

/** Where the line from a rectangle's middle towards `to` leaves the rectangle. */
export function clipToRect(p: Placement, to: Pt): Pt {
	const cx = p.x + p.w / 2;
	const cy = p.y + p.h / 2;
	const dx = to.x - cx;
	const dy = to.y - cy;
	if (dx === 0 && dy === 0) return { x: cx, y: cy };
	const t = Math.min(dx === 0 ? Infinity : p.w / 2 / Math.abs(dx), dy === 0 ? Infinity : p.h / 2 / Math.abs(dy));
	return t >= 1 ? { x: cx, y: cy } : { x: cx + dx * t, y: cy + dy * t };
}

/** A segment's line on the map: from its a, through its bends, to its b; an equipment end stops at the rectangle's edge. */
export function segmentPoints(doc: CableRouting, seg: Segment): Pt[] {
	const a = endCentre(doc, seg.a);
	const b = endCentre(doc, seg.b);
	if (!a || !b) return [];
	const mid = seg.bends.map(([x, y]) => ({ x, y }));
	const clip = (end: End, centre: Pt, next: Pt) => {
		const p = end.kind === 'equipment' ? doc.placements.find((d) => d.id === end.id) : undefined;
		return p ? clipToRect(p, next) : centre;
	};
	return [clip(seg.a, a, mid[0] ?? b), ...mid, clip(seg.b, b, mid[mid.length - 1] ?? a)];
}

const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y);

/** The point halfway along a polyline (where a segment's label goes). */
export function polylineMid(points: Pt[]): Pt {
	if (!points.length) return { x: 0, y: 0 };
	const total = points.slice(1).reduce((sum, p, i) => sum + dist(points[i], p), 0);
	let left = total / 2;
	for (let i = 1; i < points.length; i++) {
		const d = dist(points[i - 1], points[i]);
		if (left <= d && d > 0) {
			const t = left / d;
			return { x: points[i - 1].x + (points[i].x - points[i - 1].x) * t, y: points[i - 1].y + (points[i].y - points[i - 1].y) * t };
		}
		left -= d;
	}
	return points[points.length - 1];
}

/** The point of a polyline nearest to `p`: the point, which stretch it is on (0: the first), and how far away. */
export function nearestOnPolyline(points: Pt[], p: Pt): { point: Pt; index: number; distance: number } {
	let best = { point: points[0] ?? p, index: 0, distance: Infinity };
	for (let i = 1; i < points.length; i++) {
		const a = points[i - 1];
		const b = points[i];
		const len2 = (b.x - a.x) ** 2 + (b.y - a.y) ** 2;
		const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p.x - a.x) * (b.x - a.x) + (p.y - a.y) * (b.y - a.y)) / len2));
		const point = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
		const d = dist(point, p);
		if (d < best.distance) best = { point, index: i - 1, distance: d };
	}
	return best;
}

/** Put a node on a segment at `at`: the segment then ends on the node and a new segment carries on to
 *  where it ended. Both halves lose the length (it was the whole segment's). null: no node is left. */
export function splitSegment(doc: CableRouting, segId: string, at: Pt): RouteNode | null {
	const seg = doc.segments.find((s) => s.id === segId);
	if (!seg) return null;
	const { point, index } = nearestOnPolyline(segmentPoints(doc, seg), at);
	const g = doc.grid;
	const node = addNode(doc, snap(point.x, g), snap(point.y, g));
	if (!node) return null;
	const rest = addSegment(doc, { kind: 'node', id: node.id }, seg.b, seg.bends.slice(index));
	rest.ladders = JSON.parse(JSON.stringify(seg.ladders));
	seg.bends = seg.bends.slice(0, index);
	seg.b = { kind: 'node', id: node.id };
	seg.length_m = null;
	// a cable told to go through, or to keep off, the segment means both halves
	for (const o of Object.values(doc.overrides)) {
		o.via = o.via.flatMap((v) => (v === seg.id ? [seg.id, rest.id] : [v]));
		o.avoid = o.avoid.flatMap((v) => (v === seg.id ? [seg.id, rest.id] : [v]));
	}
	return node;
}

function forget(doc: CableRouting, ids: Set<string>) {
	for (const [key, o] of Object.entries(doc.overrides)) {
		o.via = o.via.filter((v) => !ids.has(v));
		o.avoid = o.avoid.filter((v) => !ids.has(v));
		if (!o.via.length && !o.avoid.length) delete doc.overrides[key];
	}
}

export function removeSegment(doc: CableRouting, id: string) {
	doc.segments = doc.segments.filter((s) => s.id !== id);
	forget(doc, new Set([id]));
}

/** Take a node or a piece of equipment off the map, with the segments that end on it. */
export function removeEnd(doc: CableRouting, end: End) {
	const gone = new Set(doc.segments.filter((s) => sameEnd(s.a, end) || sameEnd(s.b, end)).map((s) => s.id));
	doc.segments = doc.segments.filter((s) => !gone.has(s.id));
	if (end.kind === 'node') doc.nodes = doc.nodes.filter((n) => n.id !== end.id);
	else doc.placements = doc.placements.filter((p) => p.id !== end.id);
	forget(doc, new Set([...gone, end.id]));
}

/** The segments that end on a node or a piece of equipment. */
export const segmentsAt = (doc: CableRouting, end: End) => doc.segments.filter((s) => sameEnd(s.a, end) || sameEnd(s.b, end));

/** The rectangle around everything on the map; null when it is empty. */
export function bounds(doc: CableRouting): { x: number; y: number; w: number; h: number } | null {
	const xs: number[] = [];
	const ys: number[] = [];
	for (const p of doc.placements) {
		xs.push(p.x, p.x + p.w);
		ys.push(p.y, p.y + p.h);
	}
	for (const n of doc.nodes) {
		xs.push(n.x);
		ys.push(n.y);
	}
	for (const s of doc.segments) for (const [x, y] of s.bends) {
		xs.push(x);
		ys.push(y);
	}
	if (!xs.length) return null;
	const x = Math.min(...xs);
	const y = Math.min(...ys);
	return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
}

/** The view that shows the whole map in a window of `width` by `height`, with a margin. */
export function fitView(doc: CableRouting, width: number, height: number, margin = 40): ViewBox {
	const b = bounds(doc);
	if (!b || width <= 0 || height <= 0) return { scale: 1, ox: 0, oy: 0 };
	const scale = Math.max(MIN_SCALE, Math.min(2, (width - 2 * margin) / Math.max(b.w, 1), (height - 2 * margin) / Math.max(b.h, 1)));
	return { scale, ox: (width - b.w * scale) / 2 - b.x * scale, oy: (height - b.h * scale) / 2 - b.y * scale };
}

/** Zoom by `factor` keeping the point under (cx, cy) (screen) where it is. */
export function zoomAbout(v: ViewBox, factor: number, cx: number, cy: number): ViewBox {
	const scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, v.scale * factor));
	const k = scale / v.scale;
	return { scale, ox: cx - (cx - v.ox) * k, oy: cy - (cy - v.oy) * k };
}

export const toWorld = (v: ViewBox, sx: number, sy: number): Pt => ({ x: (sx - v.ox) / v.scale, y: (sy - v.oy) / v.scale });
