<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// A panel's schedule laid out like the switchboard: odd ways down the left of the chassis,
// even ways down the right, and on a three-phase panel a red, white and blue row per way.
// The quantity, watts and CB rating of a row are typed in place; a click on a description
// opens the circuit (what it is, where it sits).
import { computed } from 'vue';
import { fmt, type DistributionPanel, type PanelSchedule, type PoleRow, type PoleValues } from '../../lib/panelTypes';

const props = defineProps<{ panel: DistributionPanel; schedule: PanelSchedule; cbRatings: number[]; errors: Record<string, string> }>();
const emit = defineEmits<{ edit: [row: PoleRow]; divider: [beforeWay: number] }>();

const poles = computed(() => (props.panel.phase_type === 'three-phase' ? ['R', 'W', 'B'] : ['']));
const byCell = computed(() => new Map(props.schedule.rows.map((r) => [`${r.way}/${r.pole}`, r])));
/** The schedule in pairs of ways: each line has the left (odd way) and right (even way) row. */
const pairs = computed(() => {
	const out: { way: number; heading: string | null; lines: { left?: PoleRow; right?: PoleRow }[] }[] = [];
	for (let way = 1; way <= props.panel.ways; way += 2) {
		out.push({
			way, heading: props.panel.dividers.find((d) => d.before_way === way)?.label ?? null,
			lines: poles.value.map((p) => ({ left: byCell.value.get(`${way}/${p}`), right: byCell.value.get(`${way + 1}/${p}`) })),
		});
	}
	return out;
});

const bad = (r: PoleRow) => !!r.problem || Object.keys(props.errors).some((k) => r.entry_id !== null && k.startsWith(`${r.entry_id}.`));
const tip = (r: PoleRow) => r.problem || Object.entries(props.errors).filter(([k]) => r.entry_id !== null && k.startsWith(`${r.entry_id}.`)).map(([, m]) => m).join('; ');

function values(r: PoleRow): PoleValues | null {
	const e = props.panel.entries.find((x) => x.id === r.entry_id);
	return e ? (e.rows[r.index] ??= { cb_rating: null, qty: null, watts_each: null }) : null;
}
const typed = (r: PoleRow, f: keyof PoleValues) => values(r)?.[f] ?? '';
function set(r: PoleRow, f: keyof PoleValues, ev: Event) {
	const v = values(r);
	const text = (ev.target as HTMLInputElement).value.trim();
	const n = text === '' ? null : Number(text);
	if (v && (n === null || Number.isFinite(n))) v[f] = n === null ? null : f === 'qty' ? Math.round(n) : n;
}
</script>

<template>
	<div class="swb-wrap">
		<datalist id="dp-cb-ratings"><option v-for="a in cbRatings" :key="a" :value="a" /></datalist>
		<table class="swb" :class="panel.phase_type">
			<thead>
				<tr>
					<th class="desc">Description</th><th class="type">Load Type</th><th class="n">Qty</th><th class="n">Watts<br />(Ea.)</th>
					<th class="cct">Cct #</th><th class="n">CB<br />Rating</th>
					<th class="chassis" aria-label="Chassis"></th>
					<th class="n">CB<br />Rating</th><th class="cct">Cct #</th><th class="n">Watts<br />(Ea.)</th><th class="n">Qty</th>
					<th class="type">Load Type</th><th class="desc">Description</th>
				</tr>
			</thead>
			<tbody v-for="pair in pairs" :key="pair.way">
				<tr v-if="pair.heading !== null" class="swb-divider" @click="emit('divider', pair.way)">
					<td colspan="13" title="A heading: click to change or remove it">{{ pair.heading }}</td>
				</tr>
				<tr v-for="(line, i) in pair.lines" :key="i" :class="{ 'way-start': i === 0 }">
					<template v-for="side in (['left', 'right'] as const)" :key="side">
						<td v-if="side === 'right'" class="chassis"></td>
						<template v-for="r in [line[side]]" :key="side">
							<template v-if="r">
								<template v-for="col in (side === 'left' ? ['desc', 'type', 'qty', 'watts', 'cct', 'cb'] : ['cb', 'cct', 'watts', 'qty', 'type', 'desc'])" :key="col">
									<td v-if="col === 'desc' && r.span > 0" class="desc click" :rowspan="r.span" :class="{ spare: !r.entry_id, bad: bad(r) }"
										:title="tip(r) || (r.entry_id ? 'Click to change this circuit' : 'A spare space: click to put a circuit here')" @click="emit('edit', r)">
										<template v-if="r.entry_id">
											<strong v-if="r.tag" class="mono">{{ r.tag }}</strong> {{ r.description }}
											<span v-if="bad(r)" class="flag" aria-label="Needs attention">⚠</span>
										</template>
										<span v-else class="add">+</span>
									</td>
									<td v-else-if="col === 'type' && r.span > 0" class="type click" :rowspan="r.span" :class="{ spare: !r.entry_id || r.kind === 'spare_cb' }" @click="emit('edit', r)">{{ r.load_type }}</td>
									<td v-else-if="col === 'qty'" class="n">
										<input v-if="r.entry_id" type="number" min="0" step="1" :value="typed(r, 'qty')" :placeholder="r.qty_default ? fmt(r.qty) : ''"
											:aria-label="`${r.circuit} quantity`" @change="set(r, 'qty', $event)" />
									</td>
									<td v-else-if="col === 'watts'" class="n">
										<input v-if="r.entry_id" type="number" min="0" step="any" :value="typed(r, 'watts_each')" :placeholder="r.watts_default ? fmt(r.watts_each, 0) : ''"
											:title="r.watts_default ? 'From the load\'s rating. Type a value to replace it.' : ''" :aria-label="`${r.circuit} watts each`" @change="set(r, 'watts_each', $event)" />
									</td>
									<td v-else-if="col === 'cct'" class="cct mono" :class="r.pole ? `ph-${r.pole}` : ''">{{ r.circuit }}</td>
									<td v-else-if="col === 'cb'" class="n">
										<input v-if="r.entry_id" type="number" min="0" step="any" list="dp-cb-ratings" :value="typed(r, 'cb_rating')"
											:aria-label="`${r.circuit} CB rating`" @change="set(r, 'cb_rating', $event)" />
									</td>
								</template>
							</template>
							<td v-else colspan="6"></td>
						</template>
					</template>
				</tr>
			</tbody>
		</table>
	</div>
</template>
