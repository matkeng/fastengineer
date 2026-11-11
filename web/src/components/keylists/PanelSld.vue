<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// A panel's single line diagram, drawn from its schedule: the supply through the upstream
// circuit breaker and the isolator to the busbar, and one breaker and label per circuit.
import { computed } from 'vue';
import { SLD, sldLayout } from '../../lib/panelSld';
import { fmt, type DistributionPanel, type PanelSchedule } from '../../lib/panelTypes';

const props = defineProps<{ panel: DistributionPanel; schedule: PanelSchedule }>();
const lay = computed(() => sldLayout(props.schedule));
const three = computed(() => props.panel.phase_type === 'three-phase');
</script>

<template>
	<div class="sld-wrap">
		<svg class="sld" :viewBox="`0 0 ${lay.width} ${lay.height}`" :width="lay.width" :height="lay.height" role="img"
			:aria-label="`Single line diagram of ${schedule.tag}: ${lay.branches.length} circuit(s)`">
			<!-- the supply, the upstream circuit breaker and the isolator -->
			<g class="incomer">
				<text :x="lay.centre" y="14" text-anchor="middle" class="t-strong">{{ schedule.tag }}</text>
				<text :x="lay.centre + 14" y="44" class="t-small">Supply, {{ three ? `${fmt(panel.voltage * Math.sqrt(3), 0)}/${fmt(panel.voltage, 0)} V 3ϕ+N` : `${fmt(panel.voltage, 0)} V 1ϕ` }}</text>
				<line :x1="lay.centre" y1="24" :x2="lay.centre" y2="56" />
				<path :d="`M ${lay.centre - 5} 56 l 10 10 m -10 0 l 10 -10`" />
				<path :d="`M ${lay.centre} 66 q 12 8 0 22`" class="open" />
				<text :x="lay.centre + 14" y="80" class="t-small">Upstream CB {{ fmt(panel.upstream_cb) }} A (min)</text>
				<line :x1="lay.centre" y1="88" :x2="lay.centre" y2="104" />
				<line :x1="lay.centre" y1="104" :x2="lay.centre + 9" y2="124" />
				<circle :cx="lay.centre" cy="104" r="2.5" class="dot" />
				<circle :cx="lay.centre" cy="126" r="2.5" class="dot" />
				<text :x="lay.centre + 14" y="120" class="t-small">Isolator {{ fmt(panel.isolator_rating) }} A</text>
				<line :x1="lay.centre" y1="126" :x2="lay.centre" :y2="lay.busY" />
			</g>
			<line class="bus" :x1="lay.busX1" :y1="lay.busY" :x2="lay.busX2" :y2="lay.busY" />
			<text :x="lay.busX1" :y="lay.busY - 8" class="t-small">{{ fmt(panel.isolator_rating) }} A chassis · {{ fmt(schedule.totals.max_amps) }} A max · {{ fmt(schedule.totals.total_kw, 2) }} kW</text>

			<!-- circuits behind a heading (e.g. a lighting contactor) -->
			<g v-for="grp in lay.groups" :key="grp.label + grp.x1" class="group">
				<rect :x="grp.x1 - SLD.pitch / 2 + 3" :y="lay.busY + 12" :width="grp.x2 - grp.x1 + SLD.pitch - 6" :height="lay.height - lay.busY - 18" rx="3" />
				<text :x="grp.x1 - SLD.pitch / 2 + 9" :y="lay.height - 12" class="t-small">{{ grp.label }}</text>
			</g>

			<g v-for="b in lay.branches" :key="b.circuit + b.pole" class="branch" :class="{ spare: b.kind === 'spare_cb', bad: b.problem }">
				<title>{{ b.circuit }} {{ b.label }}{{ b.problem ? ` (${b.problem})` : '' }}</title>
				<line :x1="b.x" :y1="lay.busY" :x2="b.x" :y2="SLD.breakerY - 8" />
				<circle v-if="b.pole" :cx="b.x" :cy="lay.busY" r="5" :class="`ph ph-${b.pole}`" />
				<circle v-else :cx="b.x" :cy="lay.busY" r="3" class="dot" />
				<!-- the breaker: a cross and an open contact; three ticks for three poles -->
				<path :d="`M ${b.x - 4} ${SLD.breakerY - 12} l 8 8 m -8 0 l 8 -8`" />
				<path :d="`M ${b.x} ${SLD.breakerY - 4} q 10 7 0 18`" class="open" />
				<path v-if="b.poles === 3" :d="`M ${b.x - 6} ${SLD.breakerY + 24} l 12 -5 m -12 9 l 12 -5 m -12 9 l 12 -5`" />
				<line :x1="b.x" :y1="SLD.breakerY + 14" :x2="b.x" :y2="SLD.labelY - 6" />
				<path :d="`M ${b.x - 4} ${SLD.labelY - 12} l 4 6 l 4 -6`" class="open" />
				<g :transform="`translate(${b.x}, ${SLD.labelY}) rotate(90)`">
					<text x="0" y="-6" class="t-strong">{{ b.circuit }}<tspan v-if="b.cb" class="t-cb"> · {{ b.cb }}</tspan></text>
					<text x="0" y="8" class="t-small">{{ b.label.length > 46 ? b.label.slice(0, 45) + '…' : b.label }}<tspan v-if="b.watts"> · {{ b.watts }}</tspan></text>
				</g>
			</g>
			<text v-if="!lay.branches.length" :x="lay.centre" :y="lay.busY + 40" text-anchor="middle" class="t-small">No circuits on this panel yet.</text>
		</svg>
	</div>
</template>
