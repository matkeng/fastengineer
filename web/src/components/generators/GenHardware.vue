<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// PLC hardware for this generator: read-only. The register (systems, racks, cards and IO
// points) is the project's PLC List; this shows its cards and channels against this
// generator's latest IO list build.
import { computed, onMounted } from 'vue';
import { useGenerators } from '../../stores/generators';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';

const g = useGenerators();
const kl = useKeyLists();
const ui = useUi();
const summary = computed(() => g.hwView?.summary ?? null);

onMounted(() => g.loadHardware());

function openPlc() {
	kl.select('plc');
	ui.go('keylists');
}
</script>

<template>
	<div class="gen-panel gen-hw">
		<div class="row">
			<span class="hint">The PLC hardware register is the project's <strong>PLC List</strong> (Project lists): systems, racks, cards and IO points.</span>
			<span class="spacer" />
			<button type="button" @click="openPlc">Open PLC List</button>
		</div>
		<div v-if="summary" class="row">
			<span class="chip"><strong>{{ summary.panels }}</strong> systems</span>
			<span class="chip"><strong>{{ summary.racks }}</strong> racks</span>
			<span class="chip"><strong>{{ summary.cards }}</strong> cards</span>
			<span v-for="k in summary.by_kind.filter((x) => x.kind !== 'Network')" :key="k.kind" class="chip" :class="`kind-${k.kind}`">
				{{ k.kind }} {{ k.channels }} ch<span v-if="k.spare_cards"> ({{ k.spare_cards }} spare)</span>
			</span>
		</div>
		<div v-if="summary?.demand.length" class="hw-demand">
			<strong>Channels against the latest IO list build</strong> <span class="hint">(by the {{ summary.demand_column }} column, matched to card part numbers)</span>
			<table class="grid simple">
				<thead><tr><th>{{ summary.demand_column }}</th><th>Kind</th><th>IO points</th><th>Channels installed</th><th>Free</th></tr></thead>
				<tbody>
					<tr v-for="d in summary.demand" :key="d.card_type">
						<td>{{ d.card_type }}</td>
						<td>{{ d.kind ?? '– no card type with this part number' }}</td>
						<td>{{ d.points }}</td>
						<td>{{ d.channels }}</td>
						<td :class="{ bad: d.free < 0 }">{{ d.free }}</td>
					</tr>
				</tbody>
			</table>
		</div>
		<p v-else-if="summary" class="hint">
			<template v-if="!summary.cards">The PLC List has no cards yet.</template>
			<template v-else>The latest IO list build has no card type column to compare with (or there is no build yet).</template>
		</p>
	</div>
</template>
