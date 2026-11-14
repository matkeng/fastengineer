// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { describe, expect, it } from 'vitest';
import {
	addNode, addPlacement, addSegment, bounds, clipToRect, fitView, nearestOnPolyline, polylineMid, removeEnd, removeSegment, segmentPoints, snap,
	splitSegment, toWorld, zoomAbout,
} from './routingCanvas';
import type { CableRouting, End } from './routingTypes';

const empty = (): CableRouting => ({
	placements: [], nodes: [], segments: [], services: [], service_rules: [], default_service_id: 'lv',
	allowance: { apply_to_master: false, tail_from_m: 0, tail_to_m: 0, contingency_pct: 0, round_up_to_m: 1, route_column: 'when blank' },
	overrides: {}, next_node: 1, next_segment: 1, grid: 20, updated_at: null,
});
const node = (id: string): End => ({ kind: 'node', id });

describe('tags', () => {
	it('are given in order and not reused until they run out', () => {
		const doc = empty();
		const [a, b, c] = [addNode(doc, 0, 0)!, addNode(doc, 100, 0)!, addNode(doc, 200, 0)!];
		expect([a.tag, b.tag, c.tag]).toEqual(['N001', 'N002', 'N003']);
		removeEnd(doc, node(b.id));
		expect(addNode(doc, 0, 0)!.tag).toBe('N004');
		doc.next_node = 1000;
		expect(addNode(doc, 0, 0)!.tag).toBe('N002');
		expect(addSegment(doc, node(a.id), node(c.id)).tag).toBe('S-001');
		expect(addSegment(doc, node(a.id), node(c.id)).tag).toBe('S-002');
	});

	it('stop at 999 nodes', () => {
		const doc = empty();
		for (let i = 0; i < 999; i++) addNode(doc, i, 0);
		expect(doc.nodes[998].tag).toBe('N999');
		expect(addNode(doc, 0, 0)).toBeNull();
	});
});

describe('geometry', () => {
	it('snaps to the grid', () => {
		expect([snap(29, 20), snap(31, 20), snap(31, 0)]).toEqual([20, 40, 31]);
	});

	it('ends a segment at the edge of an equipment rectangle', () => {
		const doc = empty();
		const p = addPlacement(doc, 'MCC-1', 0, 0); // 120 x 60, middle (60, 30)
		const n = addNode(doc, 260, 30)!;
		const seg = addSegment(doc, { kind: 'equipment', id: p.id }, node(n.id), [[200, 30]]);
		expect(segmentPoints(doc, seg)).toEqual([{ x: 120, y: 30 }, { x: 200, y: 30 }, { x: 260, y: 30 }]);
		expect(clipToRect(p, { x: 60, y: 300 })).toEqual({ x: 60, y: 60 });
		expect(clipToRect(p, { x: 70, y: 35 })).toEqual({ x: 60, y: 30 }); // inside: the middle
		expect(polylineMid([{ x: 0, y: 0 }, { x: 100, y: 0 }, { x: 100, y: 100 }])).toEqual({ x: 100, y: 0 });
		expect(nearestOnPolyline([{ x: 0, y: 0 }, { x: 100, y: 0 }, { x: 100, y: 100 }], { x: 110, y: 40 })).toEqual({ point: { x: 100, y: 40 }, index: 1, distance: 10 });
	});

	it('fits and zooms about the cursor', () => {
		const doc = empty();
		expect(bounds(doc)).toBeNull();
		addNode(doc, 100, 100);
		addNode(doc, 500, 300);
		expect(bounds(doc)).toEqual({ x: 100, y: 100, w: 400, h: 200 });
		const v = fitView(doc, 880, 480);
		expect(v.scale).toBe(2);
		expect(toWorld(v, 440, 240)).toEqual({ x: 300, y: 200 }); // the middle of the map is the middle of the window
		const z = zoomAbout(v, 1.5, 100, 50);
		expect(toWorld(z, 100, 50)).toEqual(toWorld(v, 100, 50));
		expect(zoomAbout(v, 100, 0, 0).scale).toBe(6);
	});
});

describe('edits', () => {
	it('splits a segment with a new node', () => {
		const doc = empty();
		const [a, b] = [addNode(doc, 0, 0)!, addNode(doc, 200, 100)!];
		const seg = addSegment(doc, node(a.id), node(b.id), [[200, 0]]);
		seg.length_m = 30;
		seg.ladders = { lv: { width_mm: 600, max_kg_per_m: null } };
		doc.overrides = { c1: { via: [seg.id], avoid: [] } };
		const mid = splitSegment(doc, seg.id, { x: 95, y: 8 })!;
		expect([mid.tag, mid.x, mid.y]).toEqual(['N003', 100, 0]);
		const rest = doc.segments[1];
		expect([seg.b.id, seg.bends, seg.length_m]).toEqual([mid.id, [], null]);
		expect([rest.tag, rest.a.id, rest.b.id, rest.bends, rest.length_m, rest.ladders.lv.width_mm]).toEqual(['S-002', mid.id, b.id, [[200, 0]], null, 600]);
		expect(doc.overrides.c1.via).toEqual([seg.id, rest.id]);
	});

	it('takes a node off with its segments and the routes through it', () => {
		const doc = empty();
		const [a, b, c] = [addNode(doc, 0, 0)!, addNode(doc, 100, 0)!, addNode(doc, 200, 0)!];
		const ab = addSegment(doc, node(a.id), node(b.id));
		const bc = addSegment(doc, node(b.id), node(c.id));
		const ac = addSegment(doc, node(a.id), node(c.id));
		doc.overrides = { c1: { via: [b.id], avoid: [] }, c2: { via: [ac.id], avoid: [bc.id] } };
		removeEnd(doc, node(b.id));
		expect(doc.nodes.map((n) => n.tag)).toEqual(['N001', 'N003']);
		expect(doc.segments.map((s) => s.id)).toEqual([ac.id]);
		expect(doc.overrides).toEqual({ c2: { via: [ac.id], avoid: [] } });
		removeSegment(doc, ac.id);
		expect(doc.segments).toEqual([]);
		expect(doc.overrides).toEqual({});
		expect(ab.tag).toBe('S-001');
	});
});
