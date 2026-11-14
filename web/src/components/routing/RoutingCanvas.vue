<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The Cable Routing map: equipment rectangles, nodes and the segments between them, drawn as SVG.
// It is a symbolic diagram: where things are says nothing about a segment's length.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import {
	type Pt, type ViewBox, addNode, addPlacement, addSegment, fitView, polylineMid, sameEnd, segmentPoints, snap, splitSegment, toWorld, zoomAbout,
} from '../../lib/routingCanvas';
import type { CableRouting, End, Segment } from '../../lib/routingTypes';
import { MAX_NODES } from '../../lib/routingTypes';
import { useRouting } from '../../stores/routing';

const rt = useRouting();
const doc = computed(() => rt.draft as CableRouting);
const host = ref<HTMLDivElement | null>(null);
const size = reactive({ w: 0, h: 0 });
const vb = ref<ViewBox>({ scale: 1, ox: 0, oy: 0 });
const tool = ref<'select' | 'draw'>('select');
const snapOn = ref(true);
const grid = computed(() => (snapOn.value ? doc.value.grid : 0));
const note = ref('');

// -- what is drawn ---------------------------------------------------------------------------
const lines = computed(() => doc.value.segments.map((seg) => {
	const points = segmentPoints(doc.value, seg);
	return { seg, points, path: points.map((p) => `${p.x},${p.y}`).join(' '), mid: polylineMid(points), load: rt.loadById.get(seg.id) };
}).filter((l) => l.points.length > 1));
/** The segments and nodes of the selected cable's route. */
const route = computed(() => new Set(rt.selectedCable?.segments ?? []));
const routeEnds = computed(() => {
	const c = rt.selectedCable;
	return new Set(c ? [c.from_tag.trim().toLowerCase(), c.to_tag.trim().toLowerCase()] : []);
});
const stops = computed(() => {
	const o = rt.selectedCable ? doc.value.overrides[rt.selectedCable.key] : undefined;
	return { via: new Set(o?.via ?? []), avoid: new Set(o?.avoid ?? []) };
});
const selectedSegment = computed(() => (rt.selection?.kind === 'segment' ? doc.value.segments.find((s) => s.id === rt.selection?.id) ?? null : null));
const selectedPlacement = computed(() => (rt.selection?.kind === 'equipment' ? doc.value.placements.find((p) => p.id === rt.selection?.id) ?? null : null));
const isSelected = (kind: string, id: string) => rt.selection?.kind === kind && rt.selection.id === id;
const shorten = (text: string, width: number) => (text.length * 6.2 > width - 10 ? `${text.slice(0, Math.max(1, Math.floor((width - 16) / 6.2)))}…` : text);
const lengthText = (seg: Segment) => (seg.length_m === null ? '? m' : `${seg.length_m} m`);

// -- the view --------------------------------------------------------------------------------
let fitted = false;
function fit() {
	vb.value = fitView(doc.value, size.w, size.h);
}
function zoom(factor: number) {
	vb.value = zoomAbout(vb.value, factor, size.w / 2, size.h / 2);
}
function onWheel(e: WheelEvent) {
	const at = local(e);
	vb.value = zoomAbout(vb.value, e.deltaY < 0 ? 1.15 : 1 / 1.15, at.x, at.y);
}
const local = (e: MouseEvent): Pt => {
	const r = host.value!.getBoundingClientRect();
	return { x: e.clientX - r.left, y: e.clientY - r.top };
};
const world = (e: MouseEvent): Pt => {
	const p = local(e);
	return toWorld(vb.value, p.x, p.y);
};
const snapped = (p: Pt): Pt => ({ x: snap(p.x, grid.value), y: snap(p.y, grid.value) });

let observer: ResizeObserver | undefined;
onMounted(() => {
	observer = new ResizeObserver(() => {
		const r = host.value?.getBoundingClientRect();
		if (!r) return;
		size.w = r.width;
		size.h = r.height;
		if (!fitted && r.width > 0) {
			fitted = true;
			fit();
		}
	});
	if (host.value) observer.observe(host.value);
});
onBeforeUnmount(() => observer?.disconnect());

// -- the pointer -----------------------------------------------------------------------------
interface Hit { kind: 'node' | 'equipment' | 'segment' | 'label' | 'bend' | 'resize'; id: string; index: number }
function hitOf(e: Event): Hit | null {
	const el = (e.target as Element).closest?.('[data-kind]') as HTMLElement | SVGElement | null;
	return el ? { kind: el.dataset.kind as Hit['kind'], id: el.dataset.id ?? '', index: Number(el.dataset.index ?? 0) } : null;
}
type Drag =
	| { kind: 'pan'; sx: number; sy: number; ox: number; oy: number; hit: Hit | null }
	| { kind: 'move'; end: End; dx: number; dy: number }
	| { kind: 'bend'; seg: string; index: number }
	| { kind: 'resize'; id: string };
let drag: Drag | null = null;
let downHit: Hit | null = null;
let moved = false;
let downAt: Pt = { x: 0, y: 0 };
/** While a segment is being drawn: where it starts and its corners so far. */
const pending = ref<{ start: End; bends: [number, number][] } | null>(null);
const cursor = ref<Pt | null>(null);
let lastClick = { t: 0, x: 0, y: 0, addedBend: false };

function onDown(e: PointerEvent) {
	if (e.button !== 0 && e.button !== 1) return;
	host.value?.focus();
	host.value?.setPointerCapture(e.pointerId);
	moved = false;
	downAt = local(e);
	const hit = hitOf(e);
	downHit = hit;
	const pan: Drag = { kind: 'pan', sx: downAt.x, sy: downAt.y, ox: vb.value.ox, oy: vb.value.oy, hit };
	if (e.button === 1 || tool.value === 'draw' || !hit || rt.picking) {
		drag = pan;
		return;
	}
	const w = world(e);
	if (hit.kind === 'bend') drag = { kind: 'bend', seg: hit.id, index: hit.index };
	else if (hit.kind === 'resize') drag = { kind: 'resize', id: hit.id };
	else if (hit.kind === 'node' || hit.kind === 'equipment') {
		rt.select({ kind: hit.kind, id: hit.id });
		const item = hit.kind === 'node' ? doc.value.nodes.find((n) => n.id === hit.id) : doc.value.placements.find((p) => p.id === hit.id);
		drag = item ? { kind: 'move', end: { kind: hit.kind, id: hit.id }, dx: w.x - item.x, dy: w.y - item.y } : pan;
	} else {
		rt.select({ kind: 'segment', id: hit.id });
		if (hit.kind === 'label') rt.focusLength++;
		drag = pan;
	}
}

function onMove(e: PointerEvent) {
	const w = world(e);
	cursor.value = w;
	if (!drag) return;
	const at = local(e);
	if (!moved && Math.hypot(at.x - downAt.x, at.y - downAt.y) < 4) return;
	if (!moved && drag.kind !== 'pan') rt.remember();
	moved = true;
	if (drag.kind === 'pan') {
		vb.value = { ...vb.value, ox: drag.ox + at.x - drag.sx, oy: drag.oy + at.y - drag.sy };
	} else if (drag.kind === 'move') {
		const d = drag;
		const item = d.end.kind === 'node' ? doc.value.nodes.find((n) => n.id === d.end.id) : doc.value.placements.find((p) => p.id === d.end.id);
		if (item) {
			item.x = snap(w.x - d.dx, grid.value);
			item.y = snap(w.y - d.dy, grid.value);
		}
	} else if (drag.kind === 'bend') {
		const d = drag;
		const seg = doc.value.segments.find((s) => s.id === d.seg);
		if (seg?.bends[d.index]) seg.bends[d.index] = [snap(w.x, grid.value), snap(w.y, grid.value)];
	} else {
		const d = drag;
		const p = doc.value.placements.find((x) => x.id === d.id);
		if (p) {
			p.w = Math.max(40, snap(w.x - p.x, grid.value));
			p.h = Math.max(30, snap(w.y - p.y, grid.value));
		}
	}
}

function onUp(e: PointerEvent) {
	const d = drag;
	drag = null;
	if (!d) return;
	if (moved) {
		if (d.kind !== 'pan') rt.checkSoon();
		return;
	}
	const w = world(e);
	const at = local(e);
	// the pointer is captured, so the browser's own click and dblclick land on the canvas, not on what was hit
	const now = performance.now();
	const double = now - lastClick.t < 400 && Math.hypot(at.x - lastClick.x, at.y - lastClick.y) < 6;
	if (tool.value === 'select' && !rt.picking) {
		lastClick = { t: double ? 0 : now, x: at.x, y: at.y, addedBend: false };
		if (double && downHit) onDouble(downHit, w);
		else if (!downHit) rt.select(null);
		return;
	}
	if (d.kind !== 'pan') return;
	if (rt.picking) {
		if (d.hit && (d.hit.kind === 'node' || d.hit.kind === 'segment' || d.hit.kind === 'label')) rt.addStop(d.hit.id);
		return;
	}
	const addedBend = drawClick(d.hit, w, double);
	lastClick = { t: double ? 0 : now, x: at.x, y: at.y, addedBend };
}

/** A click with the Draw tool. Returns whether it added a corner (a double click then takes it back). */
function drawClick(hit: Hit | null, at: Pt, double: boolean): boolean {
	note.value = '';
	let end: End | null = null;
	if (hit?.kind === 'node' || hit?.kind === 'equipment') end = { kind: hit.kind, id: hit.id };
	else if (hit?.kind === 'segment' || hit?.kind === 'label') {
		// onto a segment: a node is put on it there
		if (pending.value && doc.value.segments.length && sameSegmentAsStart(hit.id)) return false;
		let made: End | null = null;
		rt.edit((dd) => {
			const node = splitSegment(dd, hit.id, at);
			if (node) made = { kind: 'node', id: node.id };
		});
		end = made;
		if (!end) return full();
	}
	const p = pending.value;
	if (end) {
		if (!p) pending.value = { start: end, bends: [] };
		else if (!sameEnd(p.start, end)) finish(end);
		return false;
	}
	// on empty space
	const s = snapped(at);
	if (!p) {
		const start = newNode(s);
		if (start) pending.value = { start, bends: [] };
		return false;
	}
	if (!double) {
		p.bends.push([s.x, s.y]);
		return true;
	}
	if (!lastClick.addedBend) return false; // the double click that started the segment
	p.bends.pop();
	const node = newNode(s);
	if (node) finish(node);
	return false;
}
const sameSegmentAsStart = (segId: string) => {
	const seg = doc.value.segments.find((s) => s.id === segId);
	const p = pending.value;
	return !!seg && !!p && (sameEnd(seg.a, p.start) || sameEnd(seg.b, p.start)) && !p.bends.length;
};
function full(): boolean {
	note.value = `A node map has at most ${MAX_NODES} nodes.`;
	return false;
}
function newNode(at: Pt): End | null {
	let made: End | null = null;
	rt.edit((d) => {
		const node = addNode(d, at.x, at.y);
		if (node) made = { kind: 'node', id: node.id };
	});
	if (!made) full();
	return made;
}
function finish(end: End) {
	const p = pending.value;
	if (!p) return;
	let id = '';
	rt.edit((d) => {
		id = addSegment(d, p.start, end, p.bends).id;
	});
	pending.value = null;
	rt.select({ kind: 'segment', id });
	rt.focusLength++;
}
/** The line being drawn: from its start, through its corners, to the cursor. */
const rubber = computed(() => {
	const p = pending.value;
	if (!p || !cursor.value) return '';
	const tip = snapped(cursor.value);
	const ghost: Segment = { id: '', tag: '', a: p.start, b: p.start, bends: [...p.bends, [tip.x, tip.y]], length_m: null, ladders: {} };
	return segmentPoints(doc.value, ghost).slice(0, -1).map((q) => `${q.x},${q.y}`).join(' ');
});

/** A double click with the Select tool: a node is put on a segment; a corner is taken out. */
function onDouble(hit: Hit, at: Pt) {
	if (hit.kind === 'bend') {
		rt.edit((d) => void d.segments.find((s) => s.id === hit.id)?.bends.splice(hit.index, 1));
	} else if (hit.kind === 'segment' || hit.kind === 'label') {
		let id = '';
		rt.edit((d) => {
			id = splitSegment(d, hit.id, at)?.id ?? '';
		});
		if (id) rt.select({ kind: 'node', id });
		else full();
	}
}

function onKey(e: KeyboardEvent) {
	if (e.key === 'Escape') {
		pending.value = null;
		rt.picking = null;
	} else if ((e.key === 'Delete' || e.key === 'Backspace') && rt.selection && rt.selection.kind !== 'cable') {
		e.preventDefault();
		rt.removeSelected();
	} else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
		e.preventDefault();
		if (e.shiftKey) rt.redo();
		else rt.undo();
	} else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
		e.preventDefault();
		rt.redo();
	}
}
watch(tool, () => {
	pending.value = null;
});

// -- equipment from the list -----------------------------------------------------------------
function place(item: { tag: string; description: string; source: string | null }, at: Pt) {
	let id = '';
	rt.edit((d) => {
		let x = snap(at.x - 60, d.grid);
		let y = snap(at.y - 30, d.grid);
		while (d.placements.some((p) => p.x === x && p.y === y)) {
			x += 2 * d.grid;
			y += 2 * d.grid;
		}
		id = addPlacement(d, item.tag, x, y, item.description, item.source).id;
	});
	rt.select({ kind: 'equipment', id });
}
function onDrop(e: DragEvent) {
	const data = e.dataTransfer?.getData('application/x-routing-equipment');
	if (data) place(JSON.parse(data), world(e));
}
watch(() => rt.placeRequest, (req) => {
	if (!req) return;
	place(req, toWorld(vb.value, size.w / 2, size.h / 2));
	rt.placeRequest = null;
});
const hint = computed(() => {
	if (rt.picking) return `Click the nodes and segments the cable ${rt.picking === 'via' ? 'goes through, in order' : 'keeps off'}. Esc to stop.`;
	if (tool.value === 'draw') {
		return pending.value
			? 'Click for a corner, a node or equipment to end there, or double-click empty space to end on a new node. Esc to cancel.'
			: 'Click a node or equipment to start a segment, or empty space to start at a new node.';
	}
	return 'Drag to move. Double-click a segment to put a node on it. Delete removes what is selected. Scroll to zoom.';
});
</script>

<template>
	<div class="rt-canvas-wrap">
		<div class="rt-tools">
			<span class="seg">
				<button type="button" :class="{ secondary: tool !== 'select' }" data-testid="tool-select" @click="tool = 'select'">Select</button>
				<button type="button" :class="{ secondary: tool !== 'draw' }" data-testid="tool-draw" @click="tool = 'draw'">Draw route</button>
			</span>
			<button type="button" class="secondary small" title="Show the whole map" @click="fit">Fit</button>
			<button type="button" class="secondary small" title="Zoom out" @click="zoom(1 / 1.25)">−</button>
			<button type="button" class="secondary small" title="Zoom in" @click="zoom(1.25)">+</button>
			<label class="rt-check"><input v-model="snapOn" type="checkbox" /> Snap to grid</label>
			<span class="hint rt-hint">{{ note || hint }}</span>
		</div>
		<div ref="host" class="rt-canvas" :class="[`tool-${tool}`, { picking: !!rt.picking }]" tabindex="0" data-testid="routing-canvas"
			@pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="drag = null" @wheel.prevent="onWheel"
			@keydown="onKey" @dragover.prevent @drop.prevent="onDrop">
			<svg :width="size.w" :height="size.h">
				<defs>
					<pattern id="rt-grid" :width="doc.grid * vb.scale * 5" :height="doc.grid * vb.scale * 5" patternUnits="userSpaceOnUse"
						:x="vb.ox" :y="vb.oy">
						<path :d="`M ${doc.grid * vb.scale * 5} 0 L 0 0 0 ${doc.grid * vb.scale * 5}`" class="rt-gridline" />
					</pattern>
				</defs>
				<rect :width="size.w" :height="size.h" fill="url(#rt-grid)" />
				<g :transform="`translate(${vb.ox} ${vb.oy}) scale(${vb.scale})`">
					<g v-for="l in lines" :key="l.seg.id" class="rt-segment"
						:class="[l.load?.worst ? `load-${l.load.worst}` : 'load-none', { selected: isSelected('segment', l.seg.id), unmeasured: l.seg.length_m === null,
							route: route.has(l.seg.id), via: stops.via.has(l.seg.id), avoid: stops.avoid.has(l.seg.id), dim: route.size > 0 && !route.has(l.seg.id) }]">
						<polyline class="hit" :points="l.path" data-kind="segment" :data-id="l.seg.id" />
						<polyline class="line" :points="l.path" />
						<text class="label" :x="l.mid.x" :y="l.mid.y - 8" text-anchor="middle" data-kind="label" :data-id="l.seg.id">
							{{ l.seg.tag }} · {{ lengthText(l.seg) }}
							<title>{{ l.seg.tag }}: {{ l.load?.cables.length ?? 0 }} cable(s). Click to type its length.</title>
						</text>
					</g>
					<g v-for="p in doc.placements" :key="p.id" class="rt-equipment"
						:class="{ selected: isSelected('equipment', p.id), end: routeEnds.has(p.tag.trim().toLowerCase()), bad: !!rt.errors[`${p.id}.tag`] }"
						data-kind="equipment" :data-id="p.id">
						<rect :x="p.x" :y="p.y" :width="p.w" :height="p.h" rx="2" />
						<text class="tag" :x="p.x + p.w / 2" :y="p.y + p.h / 2 - (p.description ? 3 : -4)" text-anchor="middle">{{ shorten(p.tag || '(no tag)', p.w + 20) }}</text>
						<text v-if="p.description" class="desc" :x="p.x + p.w / 2" :y="p.y + p.h / 2 + 12" text-anchor="middle">{{ shorten(p.description, p.w) }}</text>
					</g>
					<g v-for="n in doc.nodes" :key="n.id" class="rt-node" :class="{ selected: isSelected('node', n.id), via: stops.via.has(n.id) }"
						data-kind="node" :data-id="n.id">
						<circle class="hit" :cx="n.x" :cy="n.y" r="12" />
						<circle class="dot" :cx="n.x" :cy="n.y" r="6" />
						<text :x="n.x + 9" :y="n.y - 9">{{ n.tag }}</text>
					</g>
					<template v-if="selectedSegment && tool === 'select'">
						<circle v-for="(b, i) in selectedSegment.bends" :key="i" class="rt-handle" :cx="b[0]" :cy="b[1]" r="5" data-kind="bend"
							:data-id="selectedSegment.id" :data-index="i">
							<title>Drag to move the corner; double-click to remove it</title>
						</circle>
					</template>
					<rect v-if="selectedPlacement && tool === 'select'" class="rt-handle" :x="selectedPlacement.x + selectedPlacement.w - 5"
						:y="selectedPlacement.y + selectedPlacement.h - 5" width="10" height="10" data-kind="resize" :data-id="selectedPlacement.id" />
					<polyline v-if="rubber" class="rt-rubber" :points="rubber" />
				</g>
			</svg>
			<p v-if="!doc.placements.length && !doc.nodes.length" class="rt-empty hint">
				Drag equipment here from the list on the left, then choose <strong>Draw route</strong> to join it with nodes and segments.
			</p>
		</div>
	</div>
</template>
