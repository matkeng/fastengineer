<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Beside the map: what is selected (a segment's length and ladders, a cable's route...), or the map's totals and problems.
import { computed, nextTick, ref, watch } from 'vue';
import { nameKey, segmentsAt } from '../../lib/routingCanvas';
import type { CableRoute, End, LadderOverride, Segment } from '../../lib/routingTypes';
import { MAX_NODES } from '../../lib/routingTypes';
import { useRouting } from '../../stores/routing';

const rt = useRouting();
const doc = computed(() => rt.draft!);
const sel = computed(() => rt.selection);
const node = computed(() => (sel.value?.kind === 'node' ? doc.value.nodes.find((n) => n.id === sel.value?.id) ?? null : null));
const placement = computed(() => (sel.value?.kind === 'equipment' ? doc.value.placements.find((p) => p.id === sel.value?.id) ?? null : null));
const segment = computed(() => (sel.value?.kind === 'segment' ? doc.value.segments.find((s) => s.id === sel.value?.id) ?? null : null));
const cable = computed(() => rt.selectedCable);
const cables = computed(() => rt.view?.cables ?? []);
const serviceName = (id: string) => doc.value.services.find((s) => s.id === id)?.name ?? '?';
const serviceColour = (id: string) => doc.value.services.find((s) => s.id === id)?.colour ?? '#888';

const endName = (end: End) => (end.kind === 'node' ? doc.value.nodes.find((n) => n.id === end.id)?.tag : doc.value.placements.find((p) => p.id === end.id)?.tag) ?? '?';
const nameOf = (id: string) => doc.value.nodes.find((n) => n.id === id)?.tag ?? doc.value.segments.find((s) => s.id === id)?.tag ?? '?';
const attached = computed(() => {
	const s = sel.value;
	return s && (s.kind === 'node' || s.kind === 'equipment') ? segmentsAt(doc.value, { kind: s.kind, id: s.id }) : [];
});
const cablesAt = computed(() => (placement.value ? cables.value.filter((c) => [c.from_tag, c.to_tag].some((t) => nameKey(t) === nameKey(placement.value!.tag))) : []));

// -- a segment -------------------------------------------------------------------------------
const load = computed(() => (segment.value ? rt.loadById.get(segment.value.id) ?? null : null));
const segmentCables = computed(() => (load.value?.cables ?? []).map((row) => rt.cableByKey.get(String(row))).filter((c): c is CableRoute => !!c));
const lengthInput = ref<HTMLInputElement | null>(null);
watch(() => rt.focusLength, async () => {
	await nextTick();
	lengthInput.value?.focus();
	lengthInput.value?.select();
});
const number = (text: string): number | null => (text.trim() === '' || Number.isNaN(Number(text)) ? null : Number(text));
function setLength(seg: Segment, text: string) {
	const value = number(text);
	if (value === seg.length_m) return;
	rt.edit((d) => {
		const s = d.segments.find((x) => x.id === seg.id);
		if (s) s.length_m = value;
	});
}
/** Enter in the length: on to the next segment that has none. */
function nextUnmeasured(seg: Segment, text: string) {
	setLength(seg, text);
	const all = doc.value.segments;
	const from = all.findIndex((s) => s.id === seg.id);
	const next = [...all.slice(from + 1), ...all.slice(0, from)].find((s) => s.length_m === null);
	if (next) {
		rt.select({ kind: 'segment', id: next.id });
		rt.focusLength++;
	}
}
/** The services to show ladders for: those with cables on the segment, and those something is installed for. */
const ladderRows = computed(() => {
	const seg = segment.value;
	if (!seg) return [];
	return doc.value.services.filter((s) => load.value?.services.some((x) => x.service_id === s.id) || seg.ladders[s.id])
		.map((s) => ({ service: s, load: load.value?.services.find((x) => x.service_id === s.id) ?? null, installed: seg.ladders[s.id] ?? null }));
});
function setLadder(seg: Segment, serviceId: string, field: keyof LadderOverride, text: string) {
	rt.edit((d) => {
		const s = d.segments.find((x) => x.id === seg.id);
		if (!s) return;
		const o = (s.ladders[serviceId] ??= { width_mm: null, max_kg_per_m: null });
		o[field] = number(text);
		if (o.width_mm === null && o.max_kg_per_m === null) delete s.ladders[serviceId];
	});
}

// -- equipment -------------------------------------------------------------------------------
function setPlacement(field: 'tag' | 'description', text: string) {
	const id = placement.value?.id;
	rt.edit((d) => {
		const p = d.placements.find((x) => x.id === id);
		if (p) p[field] = text.trim();
	});
}

// -- nothing selected ------------------------------------------------------------------------
const summary = computed(() => {
	const by: Record<string, number> = {};
	for (const c of cables.value) by[c.status] = (by[c.status] ?? 0) + 1;
	return {
		routed: by.ok ?? 0,
		total: cables.value.length,
		other: Object.entries(by).filter(([k]) => k !== 'ok'),
		unmeasured: doc.value.segments.filter((s) => s.length_m === null).length,
		over: (rt.view?.segments ?? []).filter((s) => s.worst === 'over').length,
		full: (rt.view?.segments ?? []).filter((s) => s.worst === 'full').length,
	};
});
const problems = computed(() => [...new Set(Object.values(rt.errors))]);
function showCables(status: string) {
	rt.tab = 'cables';
	rt.cableFilter = status;
}
</script>

<template>
	<aside class="rt-inspector" data-testid="routing-inspector">
		<template v-if="segment">
			<h3>Segment <span class="mono">{{ segment.tag }}</span></h3>
			<p class="hint">{{ endName(segment.a) }} to {{ endName(segment.b) }}</p>
			<label class="field">
				<span>Length (m)</span>
				<input ref="lengthInput" type="number" min="0" step="any" :value="segment.length_m ?? ''" placeholder="not measured" data-testid="segment-length"
					@change="setLength(segment, ($event.target as HTMLInputElement).value)"
					@keydown.enter.prevent="nextUnmeasured(segment, ($event.target as HTMLInputElement).value)" />
			</label>
			<p v-if="rt.errors[`${segment.id}.length_m`]" class="error">{{ rt.errors[`${segment.id}.length_m`] }}</p>
			<p class="hint small">Enter moves on to the next segment with no length.</p>

			<h4>Ladders</h4>
			<p v-if="!ladderRows.length" class="hint">No cables use this segment.</p>
			<div v-for="r in ladderRows" :key="r.service.id" class="rt-ladder" :class="{ over: r.load?.flags.some((f) => f === 'overloaded' || f === 'ladder too narrow') }">
				<div class="head"><span class="swatch" :style="{ background: r.service.colour }" /><strong>{{ r.service.name }}</strong>
					<span v-if="r.load" class="spacer" /><span v-if="r.load">{{ r.load.cables }} cable{{ r.load.cables === 1 ? '' : 's' }}</span></div>
				<dl v-if="r.load">
					<dt>Ladder</dt><dd><strong>{{ r.load.ladders > 1 ? `${r.load.ladders} × ` : '' }}{{ r.load.width_mm ?? '–' }} mm</strong>
						<span v-if="r.load.fill_pct !== null"> ({{ r.load.fill_pct }}% full)</span></dd>
					<dt>Needed</dt><dd>{{ r.load.required_mm }} mm <span class="hint">(cables {{ r.load.sum_od_mm }} mm<template v-if="r.load.trefoils">, {{ r.load.trefoils }} trefoil{{ r.load.trefoils === 1 ? '' : 's' }}</template>)</span></dd>
					<dt>Mass</dt><dd><strong>{{ r.load.kg_per_m }} kg/m</strong><span v-if="r.load.max_kg_per_m !== null"> of {{ r.load.max_kg_per_m }}</span></dd>
				</dl>
				<ul v-if="r.load?.flags.length" class="flags"><li v-for="f in r.load.flags" :key="f">{{ f }}</li></ul>
				<div class="installed">
					<label>Installed width
						<select :value="r.installed?.width_mm ?? ''" @change="setLadder(segment, r.service.id, 'width_mm', ($event.target as HTMLSelectElement).value)">
							<option value="">by the rules</option>
							<option v-for="w in r.service.widths_mm" :key="w" :value="w">{{ w }} mm</option>
						</select>
					</label>
					<label>Limit kg/m
						<input type="number" min="0" step="any" :value="r.installed?.max_kg_per_m ?? ''" :placeholder="String(r.service.max_kg_per_m ?? '')"
							@change="setLadder(segment, r.service.id, 'max_kg_per_m', ($event.target as HTMLInputElement).value)" />
					</label>
				</div>
			</div>

			<h4>Cables <span class="count">{{ segmentCables.length }}</span></h4>
			<ul class="rt-list short">
				<li v-for="c in segmentCables" :key="c.row" @click="rt.select({ kind: 'cable', id: String(c.row) })">
					<span class="swatch" :style="{ background: serviceColour(c.service_id) }" /><span class="mono">{{ c.number || '(no number)' }}</span>
					<span class="desc">{{ c.from_tag }} → {{ c.to_tag }}</span>
				</li>
			</ul>
			<button type="button" class="secondary small danger" @click="rt.removeSelected()">Delete segment</button>
		</template>

		<template v-else-if="cable">
			<h3>Cable <span class="mono">{{ cable.number || '(no number)' }}</span></h3>
			<dl>
				<dt>From</dt><dd class="mono">{{ cable.from_tag }}</dd>
				<dt>To</dt><dd class="mono">{{ cable.to_tag }}</dd>
				<dt>Cable</dt><dd>{{ cable.cable_code || '–' }}</dd>
				<dt>Service</dt><dd><span class="swatch" :style="{ background: serviceColour(cable.service_id) }" />{{ serviceName(cable.service_id) }}</dd>
				<dt>Diameter</dt><dd>{{ cable.od_mm === null ? 'not known' : `${cable.od_mm} mm` }}</dd>
				<dt>Mass</dt><dd>{{ cable.mass_kg_per_m === null ? 'not known' : `${cable.mass_kg_per_m} kg/m` }}</dd>
				<dt>Status</dt><dd :class="cable.status === 'ok' ? 'ok-text' : 'warn'">{{ cable.status === 'ok' ? 'routed' : cable.status }}</dd>
				<dt>Route</dt><dd class="mono">{{ cable.route || '–' }}</dd>
				<dt>Route length</dt><dd>{{ cable.route_m === null ? '–' : `${cable.route_m} m` }}</dd>
				<dt>Length</dt><dd><strong>{{ cable.length_m === null ? '–' : `${cable.length_m} m` }}</strong> <span class="hint">with the allowance</span></dd>
			</dl>
			<h4>Its own route</h4>
			<template v-if="cable.key">
				<p class="hint">Without one, the cable takes the shortest way.</p>
				<div v-for="kind in (['via', 'avoid'] as const)" :key="kind" class="rt-stops">
					<span class="what">{{ kind === 'via' ? 'Goes through' : 'Keeps off' }}</span>
					<span v-for="id in doc.overrides[cable.key]?.[kind] ?? []" :key="id" class="chip mono">{{ nameOf(id) }}
						<button type="button" class="x" title="Remove" @click="rt.removeStop(kind, id)">×</button></span>
					<button type="button" class="small" :class="{ secondary: rt.picking !== kind }" :data-testid="`pick-${kind}`"
						@click="rt.picking = rt.picking === kind ? null : kind">{{ rt.picking === kind ? 'Done' : 'Pick on the map' }}</button>
				</div>
				<button v-if="doc.overrides[cable.key]" type="button" class="secondary small" @click="rt.clearRoute()">Back to the shortest way</button>
			</template>
			<p v-else class="hint">A cable with no cable number takes the shortest way; it cannot be given a route of its own.</p>
		</template>

		<template v-else-if="placement">
			<h3>Equipment</h3>
			<label class="field">
				<span>Tag</span>
				<input type="text" class="mono" :value="placement.tag" :disabled="!!placement.source" @change="setPlacement('tag', ($event.target as HTMLInputElement).value)" />
			</label>
			<p v-if="rt.errors[`${placement.id}.tag`]" class="error">{{ rt.errors[`${placement.id}.tag`] }}</p>
			<label class="field">
				<span>Description</span>
				<input type="text" :value="placement.description" :disabled="!!placement.source" @change="setPlacement('description', ($event.target as HTMLInputElement).value)" />
			</label>
			<p class="hint">{{ placement.source ? 'From the Project Master Equipment List: its tag follows the list.' : 'Typed in: cables are matched on this tag.' }}</p>
			<p>{{ cablesAt.length }} cable{{ cablesAt.length === 1 ? '' : 's' }} start or end here; {{ attached.length }} segment{{ attached.length === 1 ? '' : 's' }}.</p>
			<button type="button" class="secondary small danger" @click="rt.removeSelected()">Take off the map</button>
		</template>

		<template v-else-if="node">
			<h3>Node <span class="mono">{{ node.tag }}</span></h3>
			<p v-if="rt.errors[`${node.id}.tag`]" class="error">{{ rt.errors[`${node.id}.tag`] }}</p>
			<h4>Segments <span class="count">{{ attached.length }}</span></h4>
			<ul class="rt-list short">
				<li v-for="s in attached" :key="s.id" @click="rt.select({ kind: 'segment', id: s.id })">
					<span class="mono">{{ s.tag }}</span><span class="desc">{{ endName(s.a) }} to {{ endName(s.b) }}</span><span>{{ s.length_m === null ? '?' : s.length_m }} m</span>
				</li>
			</ul>
			<button type="button" class="secondary small danger" @click="rt.removeSelected()">Delete node</button>
		</template>

		<template v-else>
			<h3>Map</h3>
			<dl>
				<dt>Equipment</dt><dd>{{ doc.placements.length }}</dd>
				<dt>Nodes</dt><dd>{{ doc.nodes.length }} of {{ MAX_NODES }}</dd>
				<dt>Segments</dt><dd>{{ doc.segments.length }}<span v-if="summary.unmeasured" class="warn"> ({{ summary.unmeasured }} with no length)</span></dd>
				<dt>Cables routed</dt><dd><a href="#" @click.prevent="showCables('ok')">{{ summary.routed }} of {{ summary.total }}</a></dd>
				<template v-for="[status, n] in summary.other" :key="status">
					<dt class="warn">{{ status }}</dt><dd><a href="#" @click.prevent="showCables(status)">{{ n }}</a></dd>
				</template>
				<dt>Ladders</dt><dd>
					<span v-if="summary.over" class="error-text">{{ summary.over }} over</span><span v-if="summary.over && summary.full">, </span>
					<span v-if="summary.full" class="warn">{{ summary.full }} into the spare</span>
					<span v-if="!summary.over && !summary.full">all within the rules</span>
				</dd>
			</dl>
			<ul v-if="problems.length || rt.view?.warnings.length" class="warn-list">
				<li v-for="m in problems" :key="m" class="error"><strong>Fix before saving:</strong> {{ m }}</li>
				<li v-for="m in rt.view?.warnings ?? []" :key="m">{{ m }}</li>
			</ul>
			<div class="rt-legend">
				<span><i class="load-none" />no cables</span><span><i class="load-ok" />within the rules</span>
				<span><i class="load-full" />into the spare</span><span><i class="load-over" />too narrow or overloaded</span>
				<span><i class="dashed" />no length yet</span>
			</div>
		</template>
	</aside>
</template>
