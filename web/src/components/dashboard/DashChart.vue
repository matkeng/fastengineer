<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import type { RunBar } from '../../lib/dashboardTypes';

// Tags found per analysis, stacked: template (series 1) under text scan (series 2).
// One y-axis, recessive grid, a 2px surface gap between segments, rounded top ends,
// a legend, one direct label (the latest run), and a tooltip per bar.
const props = defineProps<{ runs: RunBar[] }>();
const emit = defineEmits<{ open: [id: string] }>();

const W = 520;
const H = 170;
const M = { top: 16, right: 8, bottom: 22, left: 30 };
const plotW = W - M.left - M.right;
const plotH = H - M.top - M.bottom;
const asTable = ref(false);
const hover = ref<number | null>(null);

const max = computed(() => {
	const m = Math.max(1, ...props.runs.map((r) => r.template + r.text_scan));
	// Rounded up to an even number of whole steps, so the middle tick is a whole number too.
	const step = m <= 4 ? 1 : m <= 20 ? 5 : m <= 50 ? 10 : Math.pow(10, Math.floor(Math.log10(m)));
	return Math.ceil(m / (2 * step)) * 2 * step;
});
const ticks = computed(() => [0, max.value / 2, max.value]);
const y = (v: number) => M.top + plotH - (v / max.value) * plotH;
const slot = computed(() => plotW / Math.max(props.runs.length, 1));
const barW = computed(() => Math.min(36, slot.value * 0.6));
const x = (i: number) => M.left + slot.value * i + (slot.value - barW.value) / 2;

/** A bar segment path with rounded top corners (r) when it is the top of the stack. */
function seg(x0: number, y0: number, w: number, h: number, roundTop: boolean): string {
	if (h <= 0) return '';
	const r = roundTop ? Math.min(4, w / 2, h) : 0;
	return `M${x0},${y0 + h}V${y0 + r}${r ? `Q${x0},${y0} ${x0 + r},${y0}` : ''}H${x0 + w - r}${r ? `Q${x0 + w},${y0} ${x0 + w},${y0 + r}` : ''}V${y0 + h}Z`;
}

const bars = computed(() =>
	props.runs.map((r, i) => {
		const total = r.template + r.text_scan;
		const x0 = x(i);
		const tTop = y(r.template);
		const sTop = y(total);
		const gap = r.template && r.text_scan ? 2 : 0;
		return {
			r, total, x0,
			template: seg(x0, tTop, barW.value, y(0) - tTop, !r.text_scan),
			scan: seg(x0, sTop, barW.value, Math.max(tTop - sTop - gap, 0), true),
			label: new Date(r.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
			date: new Date(r.at).toLocaleString(),
		};
	}),
);
const tip = computed(() => {
	if (hover.value === null) return null;
	const b = bars.value[hover.value];
	return { b, left: `${((b.x0 + barW.value / 2) / W) * 100}%`, top: `${(y(b.total) / H) * 100}%` };
});
</script>

<template>
	<div>
		<div class="chart-legend">
			<span><span class="key" style="background: var(--series-1)" />Template tags</span>
			<span><span class="key" style="background: var(--series-2)" />Text scan tags</span>
			<span class="spacer" style="flex: 1" />
			<button type="button" class="link small" @click="asTable = !asTable">{{ asTable ? 'Chart' : 'Table' }}</button>
		</div>
		<p v-if="!runs.length" class="chart-empty">No analyses yet.</p>
		<table v-else-if="asTable" class="grid simple">
			<thead><tr><th>Analysis</th><th>Template</th><th>Text scan</th><th>Total</th></tr></thead>
			<tbody>
				<tr v-for="b in bars" :key="b.r.id" @click="emit('open', b.r.id)">
					<td>{{ b.date }}</td><td class="num-val">{{ b.r.template }}</td><td class="num-val">{{ b.r.text_scan }}</td><td class="num-val">{{ b.total }}</td>
				</tr>
			</tbody>
		</table>
		<div v-else class="chart-wrap" @mouseleave="hover = null">
			<svg :viewBox="`0 0 ${W} ${H}`" role="img" :aria-label="`Tags found in the last ${runs.length} analyses`">
				<g class="axis">
					<template v-for="t in ticks" :key="t">
						<line v-if="t" class="gridline" :x1="M.left" :x2="W - M.right" :y1="y(t)" :y2="y(t)" />
						<text :x="M.left - 6" :y="y(t) + 3" text-anchor="end">{{ t }}</text>
					</template>
					<line class="baseline" :x1="M.left" :x2="W - M.right" :y1="y(0)" :y2="y(0)" />
				</g>
				<g v-for="(b, i) in bars" :key="b.r.id" class="bar" :class="{ hover: hover === i }">
					<path :d="b.template" fill="var(--series-1)" />
					<path :d="b.scan" fill="var(--series-2)" />
					<text v-if="i === bars.length - 1" class="total" :x="b.x0 + barW / 2" :y="y(b.total) - 4" text-anchor="middle">{{ b.total }}</text>
					<text class="label" :x="b.x0 + barW / 2" :y="H - 6" text-anchor="middle">{{ b.label }}</text>
					<rect class="hit" :x="M.left + slot * i" :y="M.top" :width="slot" :height="plotH" @mouseenter="hover = i" @click="emit('open', b.r.id)" />
				</g>
			</svg>
			<div v-if="tip" class="chart-tip" :style="{ left: tip.left, top: tip.top }">
				<div>{{ tip.b.date }}</div>
				<div><span class="key" style="background: var(--series-1); display: inline-block; width: 8px; height: 8px; margin-right: 4px" />template <span class="mono">{{ tip.b.r.template }}</span></div>
				<div><span class="key" style="background: var(--series-2); display: inline-block; width: 8px; height: 8px; margin-right: 4px" />text scan <span class="mono">{{ tip.b.r.text_scan }}</span></div>
			</div>
		</div>
	</div>
</template>
