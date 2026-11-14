<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Every segment of the map with, for each service on it, the ladder its cables need and their mass.
import { computed, ref } from 'vue';
import type { SegmentLoad } from '../../lib/routingTypes';
import { useRouting } from '../../stores/routing';

const rt = useRouting();
const search = ref('');
const only = ref<'' | 'problems' | 'used'>('');
const serviceName = (id: string) => rt.draft?.services.find((s) => s.id === id)?.name ?? '';
const serviceColour = (id: string) => rt.draft?.services.find((s) => s.id === id)?.colour ?? '#888';
const segments = computed(() => rt.view?.segments ?? []);
const shown = computed(() => {
	const q = search.value.trim().toLowerCase();
	return segments.value.filter((s) => (!q || s.tag.toLowerCase().includes(q) || s.services.some((x) => serviceName(x.service_id).toLowerCase().includes(q)))
		&& (only.value === '' || (only.value === 'used' ? s.cables.length > 0 : s.worst === 'over' || s.worst === 'full' || s.length_m === null)));
});
const totals = computed(() => ({
	length: Math.round(segments.value.reduce((sum, s) => sum + (s.length_m ?? 0), 0) * 10) / 10,
	problems: segments.value.filter((s) => s.worst === 'over' || s.worst === 'full' || s.length_m === null).length,
}));
function open(s: SegmentLoad) {
	rt.select({ kind: 'segment', id: s.id });
	rt.tab = 'map';
}
</script>

<template>
	<div class="rt-table-tab">
		<div class="rt-bar">
			<input v-model="search" type="search" placeholder="Search segments" aria-label="Search segments" />
			<span class="seg">
				<button type="button" :class="{ secondary: only !== '' }" @click="only = ''">All<span class="count">{{ segments.length }}</span></button>
				<button type="button" :class="{ secondary: only !== 'used' }" @click="only = 'used'">With cables</button>
				<button type="button" :class="{ secondary: only !== 'problems' }" @click="only = 'problems'">To look at<span class="count">{{ totals.problems }}</span></button>
			</span>
			<span class="hint">{{ totals.length }} m of ladder route in all</span>
			<span class="spacer" />
			<span v-if="rt.dirty" class="hint">Exports give the map as saved.</span>
			<button type="button" class="secondary small" :disabled="rt.busy" @click="rt.exportTable('segments', 'xlsx')">Export Excel</button>
			<button type="button" class="secondary small" :disabled="rt.busy" @click="rt.exportTable('segments', 'csv')">Export CSV</button>
		</div>
		<div class="rt-scroll">
			<table class="grid simple rt-table" data-testid="routing-segments">
				<thead>
					<tr><th>Segment</th><th class="num">Length (m)</th><th>Service</th><th class="num">Cables</th><th class="num">Trefoils</th>
						<th class="num" title="The cables side by side, a trefoil as one">Cables' width (mm)</th>
						<th class="num" title="With the spacing, the layers and the spare of the service's rules">Needed (mm)</th>
						<th class="num">Ladder (mm)</th><th class="num">Fill</th><th class="num">Mass (kg/m)</th><th class="num">Limit (kg/m)</th><th>Notes</th></tr>
				</thead>
				<tbody>
					<template v-for="s in shown" :key="s.id">
						<tr v-for="(x, i) in s.services" :key="x.service_id" class="pick" :class="[`load-${s.worst}`, { first: i === 0 }]" title="Show on the map" @click="open(s)">
							<td v-if="i === 0" class="mono" :rowspan="s.services.length">{{ s.tag }}</td>
							<td v-if="i === 0" class="num" :rowspan="s.services.length" :class="{ warn: s.length_m === null }">{{ s.length_m ?? 'none' }}</td>
							<td><span class="swatch" :style="{ background: serviceColour(x.service_id) }" />{{ serviceName(x.service_id) }}</td>
							<td class="num">{{ x.cables }}</td><td class="num">{{ x.trefoils || '' }}</td><td class="num">{{ x.sum_od_mm }}</td><td class="num">{{ x.required_mm }}</td>
							<td class="num"><strong>{{ x.ladders > 1 ? `${x.ladders} × ` : '' }}{{ x.width_mm ?? '' }}</strong></td>
							<td class="num">{{ x.fill_pct === null ? '' : `${x.fill_pct}%` }}</td>
							<td class="num"><strong>{{ x.kg_per_m }}</strong></td><td class="num">{{ x.max_kg_per_m ?? '' }}</td>
							<td :class="{ warn: x.flags.length }">{{ x.flags.join('; ') }}</td>
						</tr>
						<tr v-if="!s.services.length" class="pick first" title="Show on the map" @click="open(s)">
							<td class="mono">{{ s.tag }}</td><td class="num" :class="{ warn: s.length_m === null }">{{ s.length_m ?? 'none' }}</td>
							<td colspan="10" class="hint">no cables</td>
						</tr>
					</template>
					<tr v-if="!shown.length"><td colspan="12" class="hint">{{ segments.length ? 'No segment matches.' : 'No segments are drawn yet.' }}</td></tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
