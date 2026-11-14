<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The cables of the Project Master Cable Schedule with their routes over the map.
import { computed, ref } from 'vue';
import type { CableRoute } from '../../lib/routingTypes';
import { useRouting } from '../../stores/routing';

const rt = useRouting();
const search = ref('');
const LIMIT = 500;
const cables = computed(() => rt.view?.cables ?? []);
const serviceName = (id: string) => rt.draft?.services.find((s) => s.id === id)?.name ?? '';
const serviceColour = (id: string) => rt.draft?.services.find((s) => s.id === id)?.colour ?? '#888';
const statuses = computed(() => {
	const by = new Map<string, number>();
	for (const c of cables.value) by.set(c.status, (by.get(c.status) ?? 0) + 1);
	return [...by.entries()].sort(([a], [b]) => (a === 'ok' ? -1 : b === 'ok' ? 1 : a.localeCompare(b)));
});
const shown = computed(() => {
	const q = search.value.trim().toLowerCase();
	return cables.value.filter((c) => (!rt.cableFilter || c.status === rt.cableFilter)
		&& (!q || `${c.number} ${c.from_tag} ${c.to_tag} ${c.cable_code} ${c.route} ${serviceName(c.service_id)}`.toLowerCase().includes(q)));
});
function open(c: CableRoute) {
	rt.select({ kind: 'cable', id: String(c.row) });
	rt.tab = 'map';
}
</script>

<template>
	<div class="rt-table-tab">
		<div class="rt-bar">
			<input v-model="search" type="search" placeholder="Search cables" aria-label="Search cables" />
			<span class="seg">
				<button type="button" :class="{ secondary: rt.cableFilter !== '' }" @click="rt.cableFilter = ''">All<span class="count">{{ cables.length }}</span></button>
				<button v-for="[status, n] in statuses" :key="status" type="button" :class="{ secondary: rt.cableFilter !== status }" @click="rt.cableFilter = status">
					{{ status === 'ok' ? 'Routed' : status }}<span class="count">{{ n }}</span>
				</button>
			</span>
			<span class="spacer" />
			<span v-if="rt.dirty" class="hint">Exports give the map as saved.</span>
			<button type="button" class="secondary small" :disabled="rt.busy" @click="rt.exportTable('cables', 'xlsx')">Export Excel</button>
			<button type="button" class="secondary small" :disabled="rt.busy" @click="rt.exportTable('cables', 'csv')">Export CSV</button>
		</div>
		<div class="rt-scroll">
			<table class="grid simple rt-table" data-testid="routing-cables">
				<thead>
					<tr><th>Cable number</th><th>From</th><th>To</th><th>Cable</th><th>Service</th><th class="num">Diameter (mm)</th><th class="num">Mass (kg/m)</th>
						<th>Route</th><th class="num">Route (m)</th><th class="num">Length (m)</th><th>Status</th></tr>
				</thead>
				<tbody>
					<tr v-for="c in shown.slice(0, LIMIT)" :key="c.row" class="pick" :class="{ selected: rt.selection?.kind === 'cable' && rt.selection.id === String(c.row) }"
						title="Show on the map" @click="open(c)">
						<td class="mono">{{ c.number }}</td><td class="mono">{{ c.from_tag }}</td><td class="mono">{{ c.to_tag }}</td><td>{{ c.cable_code }}</td>
						<td><span class="swatch" :style="{ background: serviceColour(c.service_id) }" />{{ serviceName(c.service_id) }}</td>
						<td class="num">{{ c.od_mm ?? '' }}</td><td class="num">{{ c.mass_kg_per_m ?? '' }}</td>
						<td class="mono">{{ c.route }}<span v-if="c.overridden" class="chip" title="This cable has a route of its own">given</span></td>
						<td class="num">{{ c.route_m ?? '' }}</td><td class="num"><strong>{{ c.length_m ?? '' }}</strong></td>
						<td :class="c.status === 'ok' ? 'ok-text' : 'warn'">{{ c.status === 'ok' ? 'routed' : c.status }}</td>
					</tr>
					<tr v-if="!shown.length"><td colspan="11" class="hint">{{ cables.length ? 'No cable matches.' : 'The Project Master Cable Schedule has no cables yet.' }}</td></tr>
				</tbody>
			</table>
			<p v-if="shown.length > LIMIT" class="hint">The first {{ LIMIT }} of {{ shown.length }} cables are shown. Search to narrow them down, or export for all.</p>
		</div>
	</div>
</template>
